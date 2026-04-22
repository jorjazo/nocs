#!/usr/bin/env bash
set -euo pipefail

# Rebuilds bundled catalog TSVs from canonical sources.
# Run once per data refresh; commit the outputs.
#
# Requirements: curl, awk, sha256sum (coreutils).

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/src/main/resources/catalogs"
SEED_M="$OUT/seed-messier.tsv"
SEED_C="$OUT/seed-caldwell.tsv"

OPENNGC_URL="https://raw.githubusercontent.com/mattiaverga/OpenNGC/master/database_files/NGC.csv"
# IAU moved the fixed-width CSN file; this CSV tracks IAU WGSN names + coords (mirrors in-the-sky.org).
ALL_STARS_URL="https://raw.githubusercontent.com/cyschneck/iau-star-names/main/data/4_all_stars_data.csv"

mkdir -p "$OUT"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "==> downloading OpenNGC"
curl -fsSL "$OPENNGC_URL" -o "$TMP/ngc.csv"
OPENNGC_SHA=$(sha256sum "$TMP/ngc.csv" | awk '{print $1}')

echo "==> downloading IAU named stars (CSV)"
curl -fsSL "$ALL_STARS_URL" -o "$TMP/all_stars.csv"
ALL_STARS_SHA=$(sha256sum "$TMP/all_stars.csv" | awk '{print $1}')

write_header() {
  local out="$1"
  local url="$2"
  local sha="$3"
  {
    echo "# source: $url $sha"
    echo "# columns: id	primary_name	aliases	kind	ra_j2000_deg	dec_j2000_deg	constellation	magnitude	size_arcmin	notes"
  } > "$out"
}

##
## opennngc.tsv — all galaxies, nebulae, clusters, double stars
##
echo "==> building opennngc.tsv"
write_header "$OUT/opennngc.tsv" "$OPENNGC_URL" "$OPENNGC_SHA"
awk -F';' -v OFS='\t' '
  NR==1 { next }
  {
    name=$1; type=$2; ra=$3; dec=$4; const=$5
    # OpenNGC Type codes -> NOCS TargetKind
    kind="OTHER"
    if (type=="G")           kind="GALAXY"
    else if (type=="GPair"|| type=="GTrpl" || type=="GGroup") kind="GALAXY"
    else if (type=="Neb"||type=="DifN"||type=="EmN"||type=="RfN") kind="NEBULA"
    else if (type=="SNR")    kind="NEBULA"
    else if (type=="PN")     kind="PLANETARY_NEBULA"
    else if (type=="OCl")    kind="CLUSTER_OPEN"
    else if (type=="GCl")    kind="CLUSTER_GLOBULAR"
    else if (type=="Cl+N")   kind="NEBULA"
    else if (type=="**"||type=="*")  kind="DOUBLE_STAR"
    else if (type=="Dup"||type=="NonEx") next
    else if (type=="Ast")    kind="ASTERISM"

    # RA in OpenNGC is HH:MM:SS.sss → degrees
    n=split(ra,h,":"); if(n!=3){ra_deg="NaN"} else {ra_deg=(h[1]+h[2]/60+h[3]/3600)*15}
    # Dec "[-+]DD:MM:SS.ss" → degrees
    sign=1; d=dec; if(substr(d,1,1)=="-"){sign=-1;d=substr(d,2)} else if(substr(d,1,1)=="+"){d=substr(d,2)}
    n=split(d,q,":"); if(n!=3){dec_deg="NaN"} else {dec_deg=sign*(q[1]+q[2]/60+q[3]/3600)}

    # OpenNGC NGC.csv: MajAx;MinAx;…;B-Mag;V-Mag (indices shifted vs older schema)
    mag=$10; if(mag=="") mag=$9; if(mag=="") mag="NaN"
    maj=$6; min=$7; size=""
    if(maj!="") size=maj
    if(min!="") size=size (size==""?"":"x") min
    if(size=="") size="NaN"
    cname=const; if(cname=="") cname=""

    # id prefix
    id=name
    if (index(id,"NGC")==1) prefix="ngc"
    else if (index(id,"IC")==1) prefix="ic"
    else prefix="ngc"

    aliases=""
    print prefix":"id, name, aliases, kind, ra_deg, dec_deg, cname, mag, size, ""
  }
' "$TMP/ngc.csv" >> "$OUT/opennngc.tsv"

##
## messier.tsv + caldwell.tsv — look up each seed designator in opennngc.tsv
##
build_from_seed() {
  local seed="$1" out="$2" id_prefix="$3"
  write_header "$out" "$OPENNGC_URL" "$OPENNGC_SHA"
  awk -F'\t' -v OFS='\t' -v NGC="$OUT/opennngc.tsv" -v PREFIX="$id_prefix" '
    function canon(d,    rest, n) {
      if (index(d, "NGC") == 1 && length(d) > 3) {
        rest = substr(d, 4)
        if (rest ~ /^[0-9]+$/) { n = rest + 0; return sprintf("NGC%04d", n) }
      }
      if (index(d, "IC") == 1 && length(d) > 2) {
        rest = substr(d, 3)
        if (rest ~ /^[0-9]+$/) { n = rest + 0; return sprintf("IC%04d", n) }
      }
      return d
    }
    BEGIN {
      while ((getline line < NGC) > 0) {
        if (substr(line,1,1)=="#") continue
        n=split(line, f, "\t"); map[f[2]]=line
      }
      close(NGC)
    }
    /^#/ { next }
    {
      designator=$1; label=$2; aliases=$3
      key = canon(designator)
      if (!(key in map)) { printf("WARN seed miss: %s (canon %s)\n", designator, key) > "/dev/stderr"; next }
      n=split(map[key], f, "\t")
      id=PREFIX":"label
      new_aliases=designator
      if (aliases!="") new_aliases=new_aliases "," aliases
      print id, label, new_aliases, f[4], f[5], f[6], f[7], f[8], f[9], f[10]
    }
  ' "$seed" >> "$out"
}

echo "==> building messier.tsv"
build_from_seed "$SEED_M" "$OUT/messier.tsv" "messier"

echo "==> building caldwell.tsv"
build_from_seed "$SEED_C" "$OUT/caldwell.tsv" "caldwell"

##
## named-stars.tsv — IAU proper names + J2000 coords (CSV)
##
echo "==> building named-stars.tsv"
write_header "$OUT/named-stars.tsv" "$ALL_STARS_URL" "$ALL_STARS_SHA"
python3 - "$TMP/all_stars.csv" >> "$OUT/named-stars.tsv" <<'PY'
import csv, re, sys

def slug(name: str) -> str:
    s = "star:" + name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")

def ra_deg(hms: str) -> float:
    parts = hms.strip().split(".")
    if len(parts) != 3:
        return float("nan")
    h, m, sec = map(float, parts)
    return (h + m / 60.0 + sec / 3600.0) * 15.0

def dec_deg(s: str) -> float:
    s = s.strip()
    if not s:
        return float("nan")
    parts = s.split(".")
    if len(parts) == 3:
        sign = -1 if s.startswith("-") else 1
        body = s.lstrip("-+")
        deg, am, asec = map(float, body.split("."))
        return sign * (deg + am / 60.0 + asec / 3600.0)
    try:
        return float(s)
    except ValueError:
        return float("nan")

path = sys.argv[1]
with open(path, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        name = (row.get("Common Name") or "").strip()
        if not name:
            continue
        ra = ra_deg(row["Right Ascension (HH.MM.SS)"])
        dec = dec_deg(row["Declination (DD.SS)"])
        mag = (row.get("Magnitude (V, Visual)") or "").strip() or "NaN"
        aliases = (row.get("Alternative Names") or "").replace("\t", " ")
        con = ""
        oid = slug(name)
        print(
            f"{oid}\t{name}\t{aliases}\tSTAR\t{ra}\t{dec}\t{con}\t{mag}\tNaN\t",
            end="",
        )
        print()
PY

echo "==> catalog counts:"
for f in "$OUT/messier.tsv" "$OUT/caldwell.tsv" "$OUT/named-stars.tsv" "$OUT/opennngc.tsv"; do
  printf "   %-40s %s rows\n" "$(basename "$f")" "$(grep -v '^#' "$f" | wc -l)"
done

echo "done. Review diffs and commit."
