#!/usr/bin/env bash
# Test stub for the ASTAP CLI. Honours -f <fits>; writes a deterministic .ini
# next to the input file based on FAKE_ASTAP_OUTCOME (solved|failed). Sleeps
# FAKE_ASTAP_SLEEP seconds first when set, used to exercise the timeout path.
set -euo pipefail

FITS=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -f) FITS="$2"; shift 2 ;;
    -d|-ra|-spd|-r) shift 2 ;;
    -wcs) shift ;;
    *) shift ;;
  esac
done

if [[ -z "$FITS" ]]; then
  echo "no -f provided" >&2
  exit 64
fi

if [[ -n "${FAKE_ASTAP_SLEEP:-}" ]]; then
  sleep "$FAKE_ASTAP_SLEEP"
fi

INI="${FITS%.fits}.ini"
case "${FAKE_ASTAP_OUTCOME:-solved}" in
  failed)
    cat > "$INI" <<'EOF'
PLTSOLVD=F
ERROR=Less than 30 stars detected
WARNING=Insufficient stars
EOF
    exit 1
    ;;
  *)
    cat > "$INI" <<'EOF'
PLTSOLVD=T
CRVAL1=10.6847083
CRVAL2=41.269083
CRPIX1=512.0
CRPIX2=384.0
CDELT1=-0.000342222
CDELT2=0.000342222
CROTA1=12.5
CROTA2=12.5
NAXIS1=1024
NAXIS2=768
WARNING=
ERROR=
EOF
    exit 0
    ;;
esac
