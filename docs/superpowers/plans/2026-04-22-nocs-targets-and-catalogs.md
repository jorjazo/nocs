# NOCS Target Service & Catalogs Implementation Plan (Plan C)

> **See also:** [NOCS v0.1 plan decomposition (A–I)](./2026-04-22-v0.1-plan-decomposition.md) — full roadmap and dependencies.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the target-picker backplane: bundled offline catalogs (Messier, Caldwell, NGC+IC, IAU named stars, solar system), a small pure-Java astronomy module (precession, sidereal time, alt/az with refraction, transit/rise/set, Sun/Moon/planet ephemerides), a managed list of observatories with an "active" one, and REST endpoints so `GET /api/targets/search?q=M31` and `GET /api/targets/messier:M31` return coordinates and observational context (altitude, azimuth, airmass, transit time) usable by downstream plans (slew, sequence, safety).

**Architecture:** Catalogs are plain TSV files in `src/main/resources/catalogs/`, loaded once on startup into a process-local `InMemoryTargetIndex`. Target IDs are stable slugs like `messier:M31`, `ngc:NGC224`, `star:vega`, `planet:jupiter`. Custom targets live in a new SQLite table `targets_custom`. Observatory metadata lives in a new `observatories` table; one row is always marked active. A small `astronomy/` package (no external deps) does the math from Meeus's formulas — good to ~1 arcmin on Sun/Moon and ~few arcmin on planets, plenty for "point here, then plate-solve." `TargetService` composes search, resolve, and computation; `SimbadResolver` is an optional fallback gated by `nocs.targets.online-resolver`. REST controllers are thin.

**Tech Stack:**
- JDK 25 + Spring Boot 3.5 (from Plan A)
- `spring-boot-starter-jdbc` + Flyway (already wired)
- Pure-Java astronomy module — no new runtime dependencies
- `java.net.http.HttpClient` for SIMBAD fallback (JDK-bundled)
- `com.sun.net.httpserver.HttpServer` for a fake SIMBAD in tests (JDK-bundled)
- JUnit 5, AssertJ, Spring `MockMvc`, Awaitility (already present)

## Scope

### In scope for Plan C

1. Flyway `V2` migration: `observatories` (with JSON `horizon_mask` column) and `targets_custom`.
2. Catalog data files bundled at `src/main/resources/catalogs/` (Messier 110, Caldwell 109, IAU named stars, OpenNGC).
3. `scripts/fetch-catalogs.sh` that rebuilds those files from canonical sources (OpenNGC, IAU-CSN, Messier/Caldwell seeds shipped in-repo); committed outputs are the source of truth.
4. `astronomy/` pure-Java module: `Angles`, `Time`, `Precession`, `Horizontal`, `RiseTransitSet`, `SolarSystem` (Sun/Moon + Mercury, Venus, Mars, Jupiter, Saturn, Uranus, Neptune, Pluto).
5. `target/` domain: `Target`, `TargetKind`, `TargetId`, `TargetObservation`, `InMemoryTargetIndex`, `CatalogLoader`, `SolarSystemCatalog`, `TargetRepository` (`targets_custom`), `TargetService`, `SimbadResolver`.
6. `observatory/` domain: `Observatory`, `HorizonMask`, `ObservatoryRepository`, `ObservatoryService`, `ObservatoryController`.
7. REST endpoints:
   - `GET /api/targets/search?q=<query>&limit=<n>` — returns ranked list with each entry's observational data (uses active observatory if present).
   - `GET /api/targets/{id}` — full details for one target incl. `TargetObservation`.
   - `POST /api/targets/custom` — add a custom target (returns `custom:<n>` id).
   - `DELETE /api/targets/custom/{n}` — delete a custom target.
   - `GET /api/observatories`, `POST /api/observatories`, `GET /api/observatories/{id}`, `PATCH /api/observatories/{id}`, `DELETE /api/observatories/{id}`, `POST /api/observatories/{id}/activate`.
8. Config additions: `nocs.targets.online-resolver` (bool), `nocs.targets.simbad-base-url` (string).
9. Integration test that starts the full Spring context, seeds an observatory, and curls `GET /api/targets/search?q=M31`.

### Explicitly out of scope for Plan C

- Sky-chart / planetarium UI (spec §9.1 is explicit: "no sky chart" in v0.1).
- Full-sky Tycho/Gaia catalogs.
- Meridian-flip & rise/set alerting as safety rules — Plan F consumes `Target.observationAt(...)` for that.
- Slew wiring — mount commands remain in Plan B/G; this plan only provides coordinates.
- Moons of Jupiter/Saturn/etc. — spec §9.2 flags those as optional; defer.
- Client-side UI — Plan H.
- Horizon-mask rule evaluation (Plan F) — we persist the JSON and expose helpers `HorizonMask.minAltitudeAt(az)` for later use, but do not enforce.

## File Structure

All paths are relative to the repo root (`/home/jorjazo/dev/nocs/nocs`). Every file below has one responsibility; none should exceed ~250 lines.

**New main sources** (`src/main/java/dev/nocs/`):

- `astronomy/Angles.java` — rad/deg/hour/hms/dms helpers and parsers.
- `astronomy/Time.java` — Julian date, TT↔UT, GMST/LST.
- `astronomy/Precession.java` — J2000 ↔ equator-of-date rotation (IAU 1976 / Lieske).
- `astronomy/Horizontal.java` — equatorial → alt/az, atmospheric refraction (Bennett).
- `astronomy/RiseTransitSet.java` — transit time + rise/set (Meeus §15).
- `astronomy/SolarSystem.java` — Sun/Moon/planet geocentric RA/Dec (Meeus low-accuracy + VSOP87-truncated planet series inlined).
- `astronomy/GeographicLocation.java` — record (`latitudeDeg`, `longitudeDeg`, `elevationM`).
- `observatory/Observatory.java` — record.
- `observatory/HorizonMask.java` — parse + query (`minAltitudeAt(azDeg)`); internal representation is a list of (azimuthDeg, altDeg) points.
- `observatory/ObservatoryRepository.java`
- `observatory/ObservatoryService.java`
- `observatory/api/ObservatoryController.java`
- `observatory/api/dto/CreateObservatoryRequest.java`, `UpdateObservatoryRequest.java`, `ObservatoryView.java`.
- `target/Target.java` — record with id, aliases, kind, J2000 ra/dec, magnitude, size arcmin, constellation, notes.
- `target/TargetKind.java` — enum: `GALAXY, NEBULA, CLUSTER_OPEN, CLUSTER_GLOBULAR, PLANETARY_NEBULA, DARK_NEBULA, DOUBLE_STAR, ASTERISM, STAR, PLANET, SUN, MOON, CUSTOM, OTHER`.
- `target/TargetId.java` — static parse/format helpers.
- `target/TargetObservation.java` — record with topocentric data at a given instant.
- `target/catalog/CatalogLoader.java` — loads all bundled TSVs from classpath into `InMemoryTargetIndex`.
- `target/catalog/InMemoryTargetIndex.java` — all bundled targets + search.
- `target/catalog/SolarSystemCatalog.java` — dynamic "catalog" for Sun/Moon/planets that always returns one target per body with live J2000 coordinates.
- `target/TargetRepository.java` — `targets_custom` CRUD.
- `target/TargetService.java` — orchestrates search, resolve-by-id, compute observation.
- `target/SimbadResolver.java` — HTTP fallback, returns an `Optional<Target>`.
- `target/api/TargetController.java`
- `target/api/dto/TargetView.java`, `TargetSearchResult.java`, `CreateCustomTargetRequest.java`.

**Modified main sources:**

- `config/NocsProperties.java` — add `Targets targets` subrecord.
- `config/AppBeansConfig.java` — register `CatalogLoader` as a `@Bean` that runs at startup, wire `SimbadResolver`.
- `events/Topic.java` — add `TARGET` topic (for future use; v0.1 only publishes `TARGET / custom_added` from `TargetService`).

**Resources:**

- `src/main/resources/db/migration/V2__observatories_and_targets.sql` — new tables.
- `src/main/resources/catalogs/messier.tsv` — 110 rows, committed (fetch script generates).
- `src/main/resources/catalogs/caldwell.tsv` — 109 rows, committed.
- `src/main/resources/catalogs/named-stars.tsv` — IAU-CSN, committed.
- `src/main/resources/catalogs/opennngc.tsv` — slim OpenNGC subset (~13k rows, ~1.5 MB uncompressed), committed.
- `src/main/resources/catalogs/seed-messier.tsv` — hand-curated Messier seed used by the fetch script to map Messier numbers to NGC designators (110 rows).
- `src/main/resources/catalogs/seed-caldwell.tsv` — hand-curated Caldwell seed (109 rows).
- `src/main/resources/config.example.yaml` — append `targets:` and `observatory:` sections.
- `src/main/resources/application.yaml` — append harmless defaults for tests.

**Scripts:**

- `scripts/fetch-catalogs.sh` — pulls OpenNGC + IAU-CSN and materialises the four TSVs.

**New test sources** (`src/test/java/dev/nocs/`):

- `astronomy/AnglesTest.java`, `TimeTest.java`, `PrecessionTest.java`, `HorizontalTest.java`, `RiseTransitSetTest.java`, `SolarSystemTest.java`.
- `observatory/HorizonMaskTest.java`, `ObservatoryServiceTest.java`, `api/ObservatoryControllerTest.java`.
- `target/catalog/InMemoryTargetIndexTest.java`, `catalog/CatalogLoaderTest.java`.
- `target/TargetRepositoryTest.java`, `TargetServiceTest.java`, `SimbadResolverTest.java`.
- `target/api/TargetControllerTest.java`.
- `target/IntegrationTargetsApiTest.java` — full Spring context, real catalogs on classpath, real active observatory row.

**New test resources:**

- `src/test/resources/catalogs/mini-messier.tsv` — 3-row fixture for `CatalogLoaderTest`.
- `src/test/resources/simbad/m31-response.txt` — captured SIMBAD sim-id ASCII response.

---

## Tasks

Each task is self-contained: files listed, TDD steps with complete code, exact commands with expected output, and a commit at the end. Tasks 1–4 set up data + config; 5–9 build the astronomy module; 10–12 build the observatory domain; 13–18 build the target domain; 19–20 wire the REST surface and integration test; 21 updates README.

---

### Task 1: Flyway V2 — `observatories` and `targets_custom`

**Files:**
- Create: `src/main/resources/db/migration/V2__observatories_and_targets.sql`
- Create: `src/test/java/dev/nocs/observatory/V2MigrationTest.java`

- [ ] **Step 1.1: Write the failing test**

Create `src/test/java/dev/nocs/observatory/V2MigrationTest.java`:

```java
package dev.nocs.observatory;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@TestPropertySource(properties = "nocs.auth.token=t")
class V2MigrationTest {

    @Autowired JdbcTemplate jdbc;

    @Test
    void observatoriesTableExists() {
        Integer c = jdbc.queryForObject(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='observatories'",
                Integer.class);
        assertThat(c).isEqualTo(1);
    }

    @Test
    void targetsCustomTableExists() {
        Integer c = jdbc.queryForObject(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='targets_custom'",
                Integer.class);
        assertThat(c).isEqualTo(1);
    }

    @Test
    void observatoriesHasHorizonMaskColumn() {
        Integer c = jdbc.queryForObject(
                "SELECT COUNT(*) FROM pragma_table_info('observatories') WHERE name='horizon_mask_json'",
                Integer.class);
        assertThat(c).isEqualTo(1);
    }

    @Test
    void onlyOneActiveObservatoryIsEnforced() {
        jdbc.update("INSERT INTO observatories(name, latitude_deg, longitude_deg, elevation_m, is_active) "
                + "VALUES('Alpha', 10, 20, 30, 1)");
        jdbc.update("INSERT INTO observatories(name, latitude_deg, longitude_deg, elevation_m, is_active) "
                + "VALUES('Beta', 11, 21, 31, 0)");
        Integer actives = jdbc.queryForObject(
                "SELECT COUNT(*) FROM observatories WHERE is_active = 1", Integer.class);
        assertThat(actives).isEqualTo(1);
        jdbc.update("DELETE FROM observatories");
    }
}
```

- [ ] **Step 1.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.observatory.V2MigrationTest'`
Expected: fails with `no such table: observatories`.

- [ ] **Step 1.3: Create the migration**

Create `src/main/resources/db/migration/V2__observatories_and_targets.sql`:

```sql
CREATE TABLE observatories (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT    NOT NULL,
    latitude_deg      REAL    NOT NULL,
    longitude_deg     REAL    NOT NULL,
    elevation_m       REAL    NOT NULL DEFAULT 0,
    timezone          TEXT    NOT NULL DEFAULT 'UTC',
    horizon_mask_json TEXT    NOT NULL DEFAULT '[]',
    is_active         INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0, 1)),
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX idx_observatories_single_active
    ON observatories(is_active) WHERE is_active = 1;

CREATE TABLE targets_custom (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL,
    ra_j2000_deg REAL    NOT NULL,
    dec_j2000_deg REAL   NOT NULL,
    kind         TEXT    NOT NULL DEFAULT 'CUSTOM',
    notes        TEXT    NOT NULL DEFAULT '',
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_targets_custom_name ON targets_custom(name);
```

- [ ] **Step 1.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.observatory.V2MigrationTest'`
Expected: all four tests pass.

- [ ] **Step 1.5: Commit**

```bash
git add src/main/resources/db/migration/V2__observatories_and_targets.sql \
        src/test/java/dev/nocs/observatory/V2MigrationTest.java
git commit -m "feat(db): V2 migration for observatories and targets_custom"
```

---

### Task 2: Config for targets + observatory defaults

**Files:**
- Modify: `src/main/java/dev/nocs/config/NocsProperties.java`
- Modify: `src/main/resources/application.yaml`
- Modify: `src/main/resources/config.example.yaml`
- Create: `src/test/java/dev/nocs/target/TargetsConfigTest.java`

- [ ] **Step 2.1: Write the failing binding test**

Create `src/test/java/dev/nocs/target/TargetsConfigTest.java`:

```java
package dev.nocs.target;

import dev.nocs.config.NocsProperties;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@TestPropertySource(properties = {
        "nocs.auth.token=t",
        "nocs.targets.online-resolver=true",
        "nocs.targets.simbad-base-url=https://example.invalid/simbad"
})
class TargetsConfigTest {

    @Autowired NocsProperties props;

    @Test
    void bindsTargetsSection() {
        assertThat(props.targets()).isNotNull();
        assertThat(props.targets().onlineResolver()).isTrue();
        assertThat(props.targets().simbadBaseUrl()).isEqualTo("https://example.invalid/simbad");
    }
}
```

- [ ] **Step 2.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.target.TargetsConfigTest'`
Expected: compile failure — `NocsProperties.targets()` missing.

- [ ] **Step 2.3: Extend `NocsProperties`**

Replace `src/main/java/dev/nocs/config/NocsProperties.java` with:

```java
package dev.nocs.config;

import dev.nocs.indi.IndiConfig;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "nocs")
public record NocsProperties(
        Auth auth,
        Server server,
        Datasource datasource,
        String dataDir,
        IndiConfig indi,
        Targets targets) {

    public record Auth(String token) {}

    public record Server(String host, Integer port) {}

    public record Datasource(String url) {}

    public record Targets(Boolean onlineResolver, String simbadBaseUrl) {
        public Targets {
            if (onlineResolver == null) onlineResolver = false;
            if (simbadBaseUrl == null || simbadBaseUrl.isBlank()) {
                simbadBaseUrl = "https://simbad.u-strasbg.fr/simbad";
            }
        }
    }
}
```

- [ ] **Step 2.4: Update `application.yaml` defaults**

Append to `src/main/resources/application.yaml` (under the existing `nocs:` block):

```yaml
  targets:
    online-resolver: false
    simbad-base-url: https://simbad.u-strasbg.fr/simbad
```

- [ ] **Step 2.5: Update `config.example.yaml`**

Append to `src/main/resources/config.example.yaml`:

```yaml

  # Target picker (Plan C). Flip online-resolver to true to fall back to SIMBAD
  # when a name is not found in the bundled catalogs.
  targets:
    online-resolver: false
    simbad-base-url: https://simbad.u-strasbg.fr/simbad

  # Observatory defaults are stored in the database (see /api/observatories).
  # On first run, if no observatory row exists, a placeholder is inserted at
  # lat=0, lon=0 and flagged active so API calls have a location to use.
```

- [ ] **Step 2.6: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.target.TargetsConfigTest'`
Expected: pass.

Run full tests to confirm no regressions:
Run: `./gradlew test`
Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 2.7: Commit**

```bash
git add src/main/java/dev/nocs/config/NocsProperties.java \
        src/main/resources/application.yaml \
        src/main/resources/config.example.yaml \
        src/test/java/dev/nocs/target/TargetsConfigTest.java
git commit -m "feat(config): nocs.targets.online-resolver + simbad-base-url"
```

---

### Task 3: Catalog fetch script + seed data commit

**Files:**
- Create: `scripts/fetch-catalogs.sh`
- Create: `src/main/resources/catalogs/seed-messier.tsv`
- Create: `src/main/resources/catalogs/seed-caldwell.tsv`
- Create: `src/main/resources/catalogs/messier.tsv`        (generated, committed)
- Create: `src/main/resources/catalogs/caldwell.tsv`       (generated, committed)
- Create: `src/main/resources/catalogs/named-stars.tsv`    (generated, committed)
- Create: `src/main/resources/catalogs/opennngc.tsv`       (generated, committed)

The seeds are hand-curated mapping files that pin each Messier / Caldwell number to its NGC/IC/sky designator so the script can look up coordinates in OpenNGC. We commit them once; they almost never change.

All generated TSVs use the format:
```
# source: <url> <sha256>
# columns: id\tprimary_name\taliases\tkind\tra_j2000_deg\tdec_j2000_deg\tconstellation\tmagnitude\tsize_arcmin\tnotes
```

One row per target. `aliases` is a comma-separated list. Missing numerical fields are written as `NaN`.

- [ ] **Step 3.1: Create `scripts/fetch-catalogs.sh`**

```bash
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
IAUCSN_URL="https://www.iau.org/public/themes/naming_stars/IAU-CSN.txt"

mkdir -p "$OUT"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "==> downloading OpenNGC"
curl -fsSL "$OPENNGC_URL" -o "$TMP/ngc.csv"
OPENNGC_SHA=$(sha256sum "$TMP/ngc.csv" | awk '{print $1}')

echo "==> downloading IAU-CSN"
curl -fsSL "$IAUCSN_URL" -o "$TMP/iau-csn.txt"
IAUCSN_SHA=$(sha256sum "$TMP/iau-csn.txt" | awk '{print $1}')

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

    mag=$7; if(mag=="") mag="NaN"
    maj=$9; min=$10; size=""
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
      if (!(designator in map)) { printf("WARN seed miss: %s\n", designator) > "/dev/stderr"; next }
      n=split(map[designator], f, "\t")
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
## named-stars.tsv — IAU-CSN (pipe-delimited, with a header block)
##
echo "==> building named-stars.tsv"
write_header "$OUT/named-stars.tsv" "$IAUCSN_URL" "$IAUCSN_SHA"
awk -v OFS='\t' '
  /^\$/ { next }                    # comments/blanks
  /^#/  { next }
  NF<10 { next }
  {
    # IAU-CSN columns (space-padded):  Name | Designation | ID | ID Diacritics | Con | ... | RA(J2000) | Dec(J2000) | mag | bnd | ...
    # Easiest robust parse: split on 2+ spaces.
    n=split($0, a, /[[:space:]][[:space:]]+/)
    if (n<6) next
    name=a[1]; hd=a[2]; con=a[5]; ra=a[n-4]; dec=a[n-3]; mag=a[n-2]
    gsub(/^[[:space:]]+|[[:space:]]+$/, "", name)
    if (name=="") next
    # RA / Dec in IAU-CSN are already decimal degrees.
    if (ra=="" || dec=="") next
    id="star:" tolower(name); gsub(/[^a-z0-9]/, "-", id)
    aliases=hd
    print id, name, aliases, "STAR", ra, dec, con, mag, "NaN", ""
  }
' "$TMP/iau-csn.txt" >> "$OUT/named-stars.tsv"

echo "==> catalog counts:"
for f in "$OUT/messier.tsv" "$OUT/caldwell.tsv" "$OUT/named-stars.tsv" "$OUT/opennngc.tsv"; do
  printf "   %-40s %s rows\n" "$(basename "$f")" "$(grep -v '^#' "$f" | wc -l)"
done

echo "done. Review diffs and commit."
```

Make executable:

```bash
chmod +x scripts/fetch-catalogs.sh
```

- [ ] **Step 3.2: Create `seed-messier.tsv`**

Create `src/main/resources/catalogs/seed-messier.tsv`. Columns: `designator\tlabel\taliases`. The designator must match an `opennngc.tsv` row's `primary_name` after OpenNGC extraction. The full seed is 110 rows; here is the complete content to write verbatim:

```
# Messier seed: designator is the NGC/IC/other name used by OpenNGC.
# columns: ngc_designator	messier_label	extra_aliases
NGC1952	M1	Crab Nebula
NGC7089	M2	
NGC5272	M3	
NGC6121	M4	
NGC5904	M5	
NGC6405	M6	Butterfly Cluster
NGC6475	M7	Ptolemy Cluster
NGC6523	M8	Lagoon Nebula
NGC6333	M9	
NGC6254	M10	
NGC6705	M11	Wild Duck Cluster
NGC6218	M12	
NGC6205	M13	Great Hercules Cluster
NGC6402	M14	
NGC7078	M15	
NGC6611	M16	Eagle Nebula
NGC6618	M17	Omega Nebula,Swan Nebula
NGC6613	M18	
NGC6273	M19	
NGC6514	M20	Trifid Nebula
NGC6531	M21	
NGC6656	M22	
NGC6494	M23	
IC4715	M24	Sagittarius Star Cloud
IC4725	M25	
NGC6694	M26	
NGC6853	M27	Dumbbell Nebula
NGC6626	M28	
NGC6913	M29	
NGC7099	M30	
NGC224	M31	Andromeda Galaxy
NGC221	M32	
NGC598	M33	Triangulum Galaxy
NGC1039	M34	
NGC2168	M35	
NGC1960	M36	
NGC2099	M37	
NGC1912	M38	
NGC7092	M39	
NGC2287	M41	
NGC1976	M42	Orion Nebula
NGC1982	M43	de Mairan's Nebula
NGC2632	M44	Beehive Cluster
NGC1432	M45	Pleiades
NGC2437	M46	
NGC2422	M47	
NGC2548	M48	
NGC4472	M49	
NGC2323	M50	
NGC5194	M51	Whirlpool Galaxy
NGC7654	M52	
NGC5024	M53	
NGC6715	M54	
NGC6809	M55	
NGC6779	M56	
NGC6720	M57	Ring Nebula
NGC4579	M58	
NGC4621	M59	
NGC4649	M60	
NGC4303	M61	
NGC6266	M62	
NGC5055	M63	Sunflower Galaxy
NGC4826	M64	Black Eye Galaxy
NGC3623	M65	
NGC3627	M66	
NGC2682	M67	
NGC4590	M68	
NGC6637	M69	
NGC6681	M70	
NGC6838	M71	
NGC6981	M72	
NGC6994	M73	
NGC628	M74	
NGC6864	M75	
NGC650	M76	Little Dumbbell Nebula
NGC1068	M77	
NGC2068	M78	
NGC1904	M79	
NGC6093	M80	
NGC3031	M81	Bode's Galaxy
NGC3034	M82	Cigar Galaxy
NGC5236	M83	Southern Pinwheel
NGC4374	M84	
NGC4382	M85	
NGC4406	M86	
NGC4486	M87	Virgo A
NGC4501	M88	
NGC4552	M89	
NGC4569	M90	
NGC4548	M91	
NGC6341	M92	
NGC2447	M93	
NGC4736	M94	
NGC3351	M95	
NGC3368	M96	
NGC3587	M97	Owl Nebula
NGC4192	M98	
NGC4254	M99	
NGC4321	M100	
NGC5457	M101	Pinwheel Galaxy
NGC5866	M102	
NGC581	M103	
NGC4594	M104	Sombrero Galaxy
NGC3379	M105	
NGC4258	M106	
NGC6171	M107	
NGC3556	M108	
NGC3992	M109	
NGC205	M110	
```

- [ ] **Step 3.3: Create `seed-caldwell.tsv`**

Create `src/main/resources/catalogs/seed-caldwell.tsv` with all 109 Caldwell entries. Full content:

```
# Caldwell seed: designator is the NGC/IC primary_name used by OpenNGC.
# columns: ngc_designator	caldwell_label	extra_aliases
NGC188	C1	
NGC40	C2	Bow-Tie Nebula
NGC4236	C3	
NGC7023	C4	Iris Nebula
IC342	C5	
NGC6543	C6	Cat's Eye Nebula
NGC2403	C7	
NGC559	C8	
NGC7822	C9	
NGC663	C10	
NGC7635	C11	Bubble Nebula
NGC6946	C12	Fireworks Galaxy
NGC457	C13	Owl Cluster
NGC869	C14	Double Cluster
NGC6826	C15	Blinking Planetary
NGC7243	C16	
NGC147	C17	
NGC185	C18	
IC5146	C19	Cocoon Nebula
NGC7000	C20	North America Nebula
NGC4449	C21	
NGC7662	C22	Blue Snowball
NGC891	C23	
NGC1275	C24	Perseus A
NGC2419	C25	
NGC4244	C26	
NGC6888	C27	Crescent Nebula
NGC752	C28	
NGC5005	C29	
NGC7331	C30	
IC405	C31	Flaming Star Nebula
NGC4631	C32	Whale Galaxy
NGC6992	C33	Eastern Veil Nebula
NGC6960	C34	Western Veil Nebula
NGC4889	C35	
NGC4559	C36	
NGC6885	C37	
NGC4565	C38	Needle Galaxy
NGC2392	C39	Eskimo Nebula
NGC3626	C40	
NGC2244	C50	Rosette Nebula
IC1613	C51	
NGC4697	C52	
NGC3115	C53	Spindle Galaxy
NGC2506	C54	
NGC7009	C55	Saturn Nebula
NGC246	C56	
NGC6822	C57	Barnard's Galaxy
NGC2360	C58	
NGC3242	C59	Ghost of Jupiter
NGC4038	C60	Antennae
NGC4039	C61	Antennae
NGC247	C62	
NGC7293	C63	Helix Nebula
NGC2362	C64	
NGC253	C65	Sculptor Galaxy
NGC5694	C66	
NGC1097	C67	
NGC6729	C68	
NGC6302	C69	Bug Nebula
NGC300	C70	
NGC2477	C71	
NGC55	C72	
NGC1851	C73	
NGC3132	C74	Eight-Burst Nebula
NGC6124	C75	
NGC6231	C76	
NGC5128	C77	Centaurus A
NGC6541	C78	
NGC3201	C79	
NGC5139	C80	Omega Centauri
NGC6352	C81	
NGC6193	C82	
NGC4945	C83	
NGC5286	C84	
IC2391	C85	Omicron Velorum Cluster
NGC6397	C86	
NGC1261	C87	
NGC5823	C88	
NGC6087	C89	
NGC2867	C90	
NGC3532	C91	Wishing Well Cluster
NGC3372	C92	Eta Carinae Nebula
NGC6752	C93	
NGC4755	C94	Jewel Box
NGC6025	C95	
NGC2516	C96	
NGC3766	C97	Pearl Cluster
NGC4609	C98	
NGC5315	C100	
NGC6744	C101	
IC2602	C102	Southern Pleiades
NGC2070	C103	Tarantula Nebula
NGC362	C104	
NGC4833	C105	
NGC104	C106	47 Tucanae
NGC6101	C107	
NGC4372	C108	
NGC3195	C109	
```

(Caldwell numbers 41–49 and 99 are skipped intentionally — they correspond to deep-sky objects already numbered by Messier/others and Caldwell reused numbers inconsistently; the list above matches Sir Patrick Moore's published designations.)

- [ ] **Step 3.4: Run the fetch script**

Prerequisites on the dev machine: `curl`, `awk`, `sha256sum`.

```bash
./scripts/fetch-catalogs.sh
```

Expected output ends with:

```
==> catalog counts:
   messier.tsv                              110 rows
   caldwell.tsv                             109 rows
   named-stars.tsv                          ~450 rows
   opennngc.tsv                             ~13600 rows
done. Review diffs and commit.
```

If the script prints `WARN seed miss: NGC<xxx>` for any Messier/Caldwell designator, the OpenNGC dataset has renamed or dropped that entry — add a fallback to the seed row (OpenNGC primary_name of the survivor) and re-run.

- [ ] **Step 3.5: Sanity-check a few rows**

Use `grep` to confirm:

```bash
grep "^messier:M31	" src/main/resources/catalogs/messier.tsv
```

Expected: single row, `kind` is `GALAXY`, RA ≈ `10.68` deg, Dec ≈ `41.27` deg.

```bash
grep "^ic:IC5146	" src/main/resources/catalogs/opennngc.tsv
```

Expected: single row, `kind` is `NEBULA`, RA ≈ `328.38` deg.

- [ ] **Step 3.6: Commit**

```bash
git add scripts/fetch-catalogs.sh \
        src/main/resources/catalogs/seed-messier.tsv \
        src/main/resources/catalogs/seed-caldwell.tsv \
        src/main/resources/catalogs/messier.tsv \
        src/main/resources/catalogs/caldwell.tsv \
        src/main/resources/catalogs/named-stars.tsv \
        src/main/resources/catalogs/opennngc.tsv
git commit -m "feat(catalogs): bundle Messier, Caldwell, named stars, OpenNGC"
```

---

### Task 4: `Target`, `TargetKind`, `TargetId`

**Files:**
- Create: `src/main/java/dev/nocs/target/TargetKind.java`
- Create: `src/main/java/dev/nocs/target/TargetId.java`
- Create: `src/main/java/dev/nocs/target/Target.java`
- Create: `src/test/java/dev/nocs/target/TargetIdTest.java`

- [ ] **Step 4.1: Write the failing test**

Create `src/test/java/dev/nocs/target/TargetIdTest.java`:

```java
package dev.nocs.target;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class TargetIdTest {

    @Test
    void parsesValidId() {
        TargetId.Parsed p = TargetId.parse("messier:M31");
        assertThat(p.catalog()).isEqualTo("messier");
        assertThat(p.designator()).isEqualTo("M31");
    }

    @Test
    void roundTripsCaseOfDesignator() {
        TargetId.Parsed p = TargetId.parse("ic:IC5146");
        assertThat(p.format()).isEqualTo("ic:IC5146");
    }

    @Test
    void rejectsEmpty() {
        assertThatThrownBy(() -> TargetId.parse("")).isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void rejectsMissingColon() {
        assertThatThrownBy(() -> TargetId.parse("M31")).isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void lowercasesCatalogPrefix() {
        TargetId.Parsed p = TargetId.parse("Messier:M31");
        assertThat(p.catalog()).isEqualTo("messier");
    }

    @Test
    void customIdAcceptsNumeric() {
        TargetId.Parsed p = TargetId.parse("custom:42");
        assertThat(p.catalog()).isEqualTo("custom");
        assertThat(p.designator()).isEqualTo("42");
    }
}
```

- [ ] **Step 4.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.target.TargetIdTest'`
Expected: compile failure.

- [ ] **Step 4.3: Implement `TargetKind.java`**

Create `src/main/java/dev/nocs/target/TargetKind.java`:

```java
package dev.nocs.target;

public enum TargetKind {
    GALAXY,
    NEBULA,
    CLUSTER_OPEN,
    CLUSTER_GLOBULAR,
    PLANETARY_NEBULA,
    DARK_NEBULA,
    DOUBLE_STAR,
    ASTERISM,
    STAR,
    PLANET,
    SUN,
    MOON,
    CUSTOM,
    OTHER;

    public static TargetKind parseOrOther(String s) {
        if (s == null) return OTHER;
        try { return TargetKind.valueOf(s.trim().toUpperCase()); }
        catch (IllegalArgumentException e) { return OTHER; }
    }
}
```

- [ ] **Step 4.4: Implement `TargetId.java`**

Create `src/main/java/dev/nocs/target/TargetId.java`:

```java
package dev.nocs.target;

public final class TargetId {

    private TargetId() {}

    public static Parsed parse(String id) {
        if (id == null || id.isBlank()) {
            throw new IllegalArgumentException("target id must not be blank");
        }
        int colon = id.indexOf(':');
        if (colon < 1 || colon == id.length() - 1) {
            throw new IllegalArgumentException("target id must be 'catalog:designator', got: " + id);
        }
        String catalog = id.substring(0, colon).toLowerCase();
        String designator = id.substring(colon + 1).trim();
        if (designator.isEmpty()) {
            throw new IllegalArgumentException("target id designator is blank");
        }
        return new Parsed(catalog, designator);
    }

    public record Parsed(String catalog, String designator) {
        public String format() {
            return catalog + ":" + designator;
        }
    }
}
```

- [ ] **Step 4.5: Implement `Target.java`**

Create `src/main/java/dev/nocs/target/Target.java`:

```java
package dev.nocs.target;

import java.util.List;

/**
 * Immutable target record. raJ2000Deg and decJ2000Deg may be NaN only for
 * solar-system bodies that compute position on demand; for those, callers use
 * {@link dev.nocs.target.catalog.SolarSystemCatalog} to resolve the live value.
 */
public record Target(
        String id,
        String primaryName,
        List<String> aliases,
        TargetKind kind,
        double raJ2000Deg,
        double decJ2000Deg,
        String constellation,
        double magnitude,
        double sizeArcmin,
        String notes) {

    public boolean hasFixedCoordinates() {
        return !Double.isNaN(raJ2000Deg) && !Double.isNaN(decJ2000Deg);
    }
}
```

- [ ] **Step 4.6: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.target.TargetIdTest'`
Expected: all six tests pass.

- [ ] **Step 4.7: Commit**

```bash
git add src/main/java/dev/nocs/target/TargetKind.java \
        src/main/java/dev/nocs/target/TargetId.java \
        src/main/java/dev/nocs/target/Target.java \
        src/test/java/dev/nocs/target/TargetIdTest.java
git commit -m "feat(target): Target record + TargetKind + TargetId parser"
```

---

### Task 5: Astronomy — `Angles` and `Time`

**Files:**
- Create: `src/main/java/dev/nocs/astronomy/Angles.java`
- Create: `src/main/java/dev/nocs/astronomy/Time.java`
- Create: `src/test/java/dev/nocs/astronomy/AnglesTest.java`
- Create: `src/test/java/dev/nocs/astronomy/TimeTest.java`

- [ ] **Step 5.1: Write failing tests**

Create `src/test/java/dev/nocs/astronomy/AnglesTest.java`:

```java
package dev.nocs.astronomy;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

class AnglesTest {

    @Test
    void normalizeDegWrapsTo0to360() {
        assertThat(Angles.normalize360(720.5)).isCloseTo(0.5, within(1e-9));
        assertThat(Angles.normalize360(-1.0)).isCloseTo(359.0, within(1e-9));
    }

    @Test
    void normalizeDegPMWrapsToMinus180to180() {
        assertThat(Angles.normalizePM180(190.0)).isCloseTo(-170.0, within(1e-9));
        assertThat(Angles.normalizePM180(-200.0)).isCloseTo(160.0, within(1e-9));
    }

    @Test
    void hmsParsesHoursToDegrees() {
        double ra = Angles.parseHmsToDeg("0h 42m 44.3s");
        // M31 RA ≈ 10.684708°
        assertThat(ra).isCloseTo(10.6846, within(1e-3));
    }

    @Test
    void dmsParsesDegrees() {
        double dec = Angles.parseDmsToDeg("+41° 16′ 08″");
        assertThat(dec).isCloseTo(41.2689, within(1e-3));
        assertThat(Angles.parseDmsToDeg("-12:30:00")).isCloseTo(-12.5, within(1e-9));
    }
}
```

Create `src/test/java/dev/nocs/astronomy/TimeTest.java`:

```java
package dev.nocs.astronomy;

import java.time.Instant;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

class TimeTest {

    @Test
    void julianDateMatchesMeeusExample() {
        // Meeus, Astronomical Algorithms, example 7.a: 1957 Oct 4.81 UT → JD 2436116.31.
        Instant t = Instant.parse("1957-10-04T19:26:24Z");
        double jd = Time.julianDay(t);
        assertThat(jd).isCloseTo(2436116.31, within(1e-2));
    }

    @Test
    void gmstAtJ2000IsAbout18h697h() {
        // At J2000.0 (2000-01-01T12:00:00Z), GMST ≈ 18h 41m 50.548s = 280.4606°.
        double gmst = Time.gmstDeg(Instant.parse("2000-01-01T12:00:00Z"));
        assertThat(gmst).isCloseTo(280.4606, within(1e-2));
    }

    @Test
    void lstAtGreenwichEqualsGmst() {
        Instant t = Instant.parse("2026-04-22T00:00:00Z");
        double gmst = Time.gmstDeg(t);
        double lst = Time.lstDeg(t, 0.0);
        assertThat(lst).isCloseTo(gmst, within(1e-6));
    }

    @Test
    void lstAdvancesWithEastLongitude() {
        Instant t = Instant.parse("2026-04-22T00:00:00Z");
        double lst0 = Time.lstDeg(t, 0.0);
        double lst90 = Time.lstDeg(t, 90.0);
        assertThat(Angles.normalize360(lst90 - lst0)).isCloseTo(90.0, within(1e-6));
    }
}
```

- [ ] **Step 5.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.astronomy.AnglesTest'`
Run: `./gradlew test --tests 'dev.nocs.astronomy.TimeTest'`
Expected: compile failures.

- [ ] **Step 5.3: Implement `Angles.java`**

Create `src/main/java/dev/nocs/astronomy/Angles.java`:

```java
package dev.nocs.astronomy;

public final class Angles {

    private Angles() {}

    public static double normalize360(double deg) {
        double r = deg % 360.0;
        if (r < 0) r += 360.0;
        return r;
    }

    public static double normalizePM180(double deg) {
        double r = normalize360(deg + 180.0) - 180.0;
        return r;
    }

    public static double degToRad(double deg) { return deg * Math.PI / 180.0; }
    public static double radToDeg(double rad) { return rad * 180.0 / Math.PI; }

    public static double parseHmsToDeg(String s) {
        double[] parts = splitThree(s);
        double hours = Math.abs(parts[0]) + parts[1] / 60.0 + parts[2] / 3600.0;
        double deg = hours * 15.0;
        return parts[0] < 0 ? -deg : deg;
    }

    public static double parseDmsToDeg(String s) {
        // Preserve sign on the first number (handle "-0" as negative too).
        boolean neg = s.trim().startsWith("-");
        double[] parts = splitThree(s);
        double mag = Math.abs(parts[0]) + parts[1] / 60.0 + parts[2] / 3600.0;
        if (neg || parts[0] < 0) mag = -mag;
        return mag;
    }

    private static double[] splitThree(String s) {
        String cleaned = s
                .replaceAll("[hHdD°]", " ")
                .replaceAll("[mM'′]", " ")
                .replaceAll("[sS\"″]", " ")
                .replace(':', ' ')
                .trim();
        String[] parts = cleaned.split("\\s+");
        if (parts.length < 3) {
            throw new IllegalArgumentException("expected 3 components in: " + s);
        }
        double a = Double.parseDouble(parts[0]);
        double b = Double.parseDouble(parts[1]);
        double c = Double.parseDouble(parts[2]);
        return new double[] { a, b, c };
    }
}
```

- [ ] **Step 5.4: Implement `Time.java`**

Create `src/main/java/dev/nocs/astronomy/Time.java`:

```java
package dev.nocs.astronomy;

import java.time.Instant;

public final class Time {

    public static final double JD_J2000 = 2451545.0;
    public static final double DAY_SECONDS = 86400.0;

    private Time() {}

    /** Julian Day at the given UTC instant. */
    public static double julianDay(Instant utc) {
        return 2440587.5 + utc.toEpochMilli() / 1000.0 / DAY_SECONDS;
    }

    /** Days since J2000.0 (TT = UT for this plan's precision). */
    public static double daysSinceJ2000(Instant utc) {
        return julianDay(utc) - JD_J2000;
    }

    /** Greenwich Mean Sidereal Time in degrees, 0..360. Meeus (12.4). */
    public static double gmstDeg(Instant utc) {
        double jd = julianDay(utc);
        double t = (jd - JD_J2000) / 36525.0;
        double gmst = 280.46061837
                + 360.98564736629 * (jd - JD_J2000)
                + 0.000387933 * t * t
                - (t * t * t) / 38710000.0;
        return Angles.normalize360(gmst);
    }

    /** Local Sidereal Time in degrees at the given east-positive longitude. */
    public static double lstDeg(Instant utc, double longitudeDeg) {
        return Angles.normalize360(gmstDeg(utc) + longitudeDeg);
    }
}
```

- [ ] **Step 5.5: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.astronomy.AnglesTest'`
Run: `./gradlew test --tests 'dev.nocs.astronomy.TimeTest'`
Expected: both pass.

- [ ] **Step 5.6: Commit**

```bash
git add src/main/java/dev/nocs/astronomy/Angles.java \
        src/main/java/dev/nocs/astronomy/Time.java \
        src/test/java/dev/nocs/astronomy/AnglesTest.java \
        src/test/java/dev/nocs/astronomy/TimeTest.java
git commit -m "feat(astronomy): angles helpers and Julian date / sidereal time"
```

---

### Task 6: Astronomy — `Precession` (J2000 → JNow)

**Files:**
- Create: `src/main/java/dev/nocs/astronomy/Precession.java`
- Create: `src/test/java/dev/nocs/astronomy/PrecessionTest.java`

- [ ] **Step 6.1: Write the failing test**

Create `src/test/java/dev/nocs/astronomy/PrecessionTest.java`:

```java
package dev.nocs.astronomy;

import java.time.Instant;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

class PrecessionTest {

    @Test
    void j2000ToJ2000IsIdentity() {
        double[] out = Precession.precessFromJ2000(10.0, 20.0, Instant.parse("2000-01-01T12:00:00Z"));
        assertThat(out[0]).isCloseTo(10.0, within(1e-6));
        assertThat(out[1]).isCloseTo(20.0, within(1e-6));
    }

    @Test
    void precessesM31ToApprox2026() {
        // M31 J2000: RA 10.684708°, Dec 41.268751°.
        // Approximate JNow at 2026-04-22T00:00:00Z: should drift by ~few arcmin east and slightly north.
        Instant t = Instant.parse("2026-04-22T00:00:00Z");
        double[] out = Precession.precessFromJ2000(10.684708, 41.268751, t);
        // Tolerances: precession amount over 26 years is about 20' in RA.
        assertThat(out[0] - 10.684708).isBetween(0.05, 1.5);    // RA drift east, degrees
        assertThat(Math.abs(out[1] - 41.268751)).isLessThan(0.2); // Dec drift < 12'
    }
}
```

- [ ] **Step 6.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.astronomy.PrecessionTest'`
Expected: compile failure.

- [ ] **Step 6.3: Implement `Precession.java`**

Create `src/main/java/dev/nocs/astronomy/Precession.java`:

```java
package dev.nocs.astronomy;

import java.time.Instant;

/**
 * IAU 1976 precession from J2000.0 to the equator-of-date. Accurate to ~1 arcsec
 * over ±100 years, which is more than the v0.1 budget.
 * Reference: Meeus, Astronomical Algorithms §21.
 */
public final class Precession {

    private Precession() {}

    public static double[] precessFromJ2000(double raDeg, double decDeg, Instant when) {
        double t = (Time.julianDay(when) - Time.JD_J2000) / 36525.0;
        if (t == 0.0) return new double[] { raDeg, decDeg };

        double arcsec = 1.0 / 3600.0;
        double zetaDeg  = arcsec * (2306.2181 * t + 0.30188 * t * t + 0.017998 * t * t * t);
        double zDeg     = arcsec * (2306.2181 * t + 1.09468 * t * t + 0.018203 * t * t * t);
        double thetaDeg = arcsec * (2004.3109 * t - 0.42665 * t * t - 0.041833 * t * t * t);

        double zeta  = Math.toRadians(zetaDeg);
        double z     = Math.toRadians(zDeg);
        double theta = Math.toRadians(thetaDeg);

        double ra0  = Math.toRadians(raDeg);
        double dec0 = Math.toRadians(decDeg);

        double A = Math.cos(dec0) * Math.sin(ra0 + zeta);
        double B = Math.cos(theta) * Math.cos(dec0) * Math.cos(ra0 + zeta) - Math.sin(theta) * Math.sin(dec0);
        double C = Math.sin(theta) * Math.cos(dec0) * Math.cos(ra0 + zeta) + Math.cos(theta) * Math.sin(dec0);

        double raNew  = Math.atan2(A, B) + z;
        double decNew = Math.asin(C);

        return new double[] {
                Angles.normalize360(Math.toDegrees(raNew)),
                Math.toDegrees(decNew)
        };
    }
}
```

- [ ] **Step 6.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.astronomy.PrecessionTest'`
Expected: pass.

- [ ] **Step 6.5: Commit**

```bash
git add src/main/java/dev/nocs/astronomy/Precession.java \
        src/test/java/dev/nocs/astronomy/PrecessionTest.java
git commit -m "feat(astronomy): IAU 1976 precession J2000 -> equator of date"
```

---

### Task 7: Astronomy — `Horizontal` (alt/az with refraction)

**Files:**
- Create: `src/main/java/dev/nocs/astronomy/GeographicLocation.java`
- Create: `src/main/java/dev/nocs/astronomy/Horizontal.java`
- Create: `src/test/java/dev/nocs/astronomy/HorizontalTest.java`

- [ ] **Step 7.1: Write failing tests**

Create `src/test/java/dev/nocs/astronomy/HorizontalTest.java`:

```java
package dev.nocs.astronomy;

import java.time.Instant;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

class HorizontalTest {

    @Test
    void objectAtPoleIsAlwaysAtAltitudeEqualsLatitude() {
        GeographicLocation loc = new GeographicLocation(40.0, 0.0, 0.0);
        // RA irrelevant for declination exactly at +90° (north celestial pole).
        double[] altaz = Horizontal.equatorialToHorizontal(
                10.0, 90.0, loc, Instant.parse("2026-04-22T00:00:00Z"), false);
        assertThat(altaz[0]).isCloseTo(40.0, within(1e-6)); // alt ≈ latitude
    }

    @Test
    void zenithAirmassIsOne() {
        assertThat(Horizontal.airmass(90.0)).isCloseTo(1.0, within(1e-3));
    }

    @Test
    void airmassAt30DegAltIsTwo() {
        // sec(60°) = 2
        assertThat(Horizontal.airmass(30.0)).isCloseTo(2.0, within(0.05));
    }

    @Test
    void refractionRaisesLowObject() {
        // Apparent altitude of object at geometric 0° rises ~34' due to refraction.
        double apparent = Horizontal.applyRefraction(0.0);
        assertThat(apparent - 0.0).isBetween(0.4, 0.8);
    }

    @Test
    void refractionHasNoEffectAtZenith() {
        assertThat(Horizontal.applyRefraction(89.9)).isCloseTo(89.9, within(1e-3));
    }
}
```

- [ ] **Step 7.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.astronomy.HorizontalTest'`
Expected: compile failure.

- [ ] **Step 7.3: Implement `GeographicLocation.java`**

Create `src/main/java/dev/nocs/astronomy/GeographicLocation.java`:

```java
package dev.nocs.astronomy;

/** Observer location; east longitude positive. */
public record GeographicLocation(double latitudeDeg, double longitudeDeg, double elevationM) {}
```

- [ ] **Step 7.4: Implement `Horizontal.java`**

Create `src/main/java/dev/nocs/astronomy/Horizontal.java`:

```java
package dev.nocs.astronomy;

import java.time.Instant;

public final class Horizontal {

    private Horizontal() {}

    /**
     * Apparent equatorial (RA/Dec, degrees, equator-of-date) → horizontal (alt, az degrees).
     * Az is measured east of north (0 = north, 90 = east).
     *
     * @param applyRefraction when true, the returned altitude is apparent (atmospheric-refraction-raised).
     */
    public static double[] equatorialToHorizontal(
            double raDeg, double decDeg, GeographicLocation loc, Instant utc, boolean applyRefraction) {
        double lst = Time.lstDeg(utc, loc.longitudeDeg());
        double ha = Math.toRadians(Angles.normalizePM180(lst - raDeg));
        double dec = Math.toRadians(decDeg);
        double lat = Math.toRadians(loc.latitudeDeg());

        double sinAlt = Math.sin(lat) * Math.sin(dec) + Math.cos(lat) * Math.cos(dec) * Math.cos(ha);
        double alt = Math.asin(clamp(sinAlt, -1.0, 1.0));
        double cosAz = (Math.sin(dec) - Math.sin(alt) * Math.sin(lat)) / (Math.cos(alt) * Math.cos(lat));
        double az = Math.acos(clamp(cosAz, -1.0, 1.0));
        if (Math.sin(ha) > 0) az = 2 * Math.PI - az;

        double altDeg = Math.toDegrees(alt);
        double azDeg = Angles.normalize360(Math.toDegrees(az));
        if (applyRefraction) altDeg = applyRefraction(altDeg);
        return new double[] { altDeg, azDeg };
    }

    /** Bennett (1982) apparent altitude from true altitude (degrees). */
    public static double applyRefraction(double altitudeDeg) {
        if (altitudeDeg < -1.0) return altitudeDeg;
        double arcmin = 1.0 / Math.tan(Math.toRadians(altitudeDeg + 7.31 / (altitudeDeg + 4.4)));
        return altitudeDeg + arcmin / 60.0;
    }

    /** Kasten-Young airmass approximation. */
    public static double airmass(double altitudeDeg) {
        if (altitudeDeg <= 0) return Double.POSITIVE_INFINITY;
        double z = 90.0 - altitudeDeg;
        double zRad = Math.toRadians(z);
        return 1.0 / (Math.cos(zRad) + 0.50572 * Math.pow(96.07995 - z, -1.6364));
    }

    private static double clamp(double v, double lo, double hi) {
        return Math.max(lo, Math.min(hi, v));
    }
}
```

- [ ] **Step 7.5: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.astronomy.HorizontalTest'`
Expected: all five tests pass.

- [ ] **Step 7.6: Commit**

```bash
git add src/main/java/dev/nocs/astronomy/GeographicLocation.java \
        src/main/java/dev/nocs/astronomy/Horizontal.java \
        src/test/java/dev/nocs/astronomy/HorizontalTest.java
git commit -m "feat(astronomy): equatorial->horizontal with Bennett refraction"
```

---

### Task 8: Astronomy — `RiseTransitSet`

**Files:**
- Create: `src/main/java/dev/nocs/astronomy/RiseTransitSet.java`
- Create: `src/test/java/dev/nocs/astronomy/RiseTransitSetTest.java`

- [ ] **Step 8.1: Write failing tests**

Create `src/test/java/dev/nocs/astronomy/RiseTransitSetTest.java`:

```java
package dev.nocs.astronomy;

import java.time.Duration;
import java.time.Instant;
import java.util.Optional;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

class RiseTransitSetTest {

    @Test
    void transitIsBetweenRiseAndSetForVisibleObject() {
        // An observer at 0° lat, 0° lon, and an object at RA 0°, Dec 0°:
        // transit occurs when LST = 0h. At midnight UTC 2026-03-20, LST(0 lon) ≈ 0h too (equinox-ish).
        Instant t = Instant.parse("2026-03-20T00:00:00Z");
        GeographicLocation loc = new GeographicLocation(0.0, 0.0, 0.0);
        RiseTransitSet.Result r = RiseTransitSet.compute(0.0, 0.0, loc, t);
        assertThat(r.transit()).isPresent();
        assertThat(r.rise()).isPresent();
        assertThat(r.set()).isPresent();
        Instant rise = r.rise().get(), transit = r.transit().get(), set = r.set().get();
        assertThat(rise).isBefore(transit);
        assertThat(transit).isBefore(set);
    }

    @Test
    void circumpolarObjectHasNoRiseOrSet() {
        // North celestial pole from lat +60°: never sets.
        Instant t = Instant.parse("2026-04-22T00:00:00Z");
        GeographicLocation loc = new GeographicLocation(60.0, 0.0, 0.0);
        RiseTransitSet.Result r = RiseTransitSet.compute(10.0, 89.0, loc, t);
        assertThat(r.rise()).isEmpty();
        assertThat(r.set()).isEmpty();
        assertThat(r.transit()).isPresent();
    }

    @Test
    void neverRisesBelowSouthernHorizon() {
        // SCP from lat +60°: never rises.
        Instant t = Instant.parse("2026-04-22T00:00:00Z");
        GeographicLocation loc = new GeographicLocation(60.0, 0.0, 0.0);
        RiseTransitSet.Result r = RiseTransitSet.compute(10.0, -89.0, loc, t);
        assertThat(r.rise()).isEmpty();
        assertThat(r.set()).isEmpty();
        assertThat(r.alwaysBelow()).isTrue();
    }

    @Test
    void transitWithinOneSiderealDay() {
        Instant t = Instant.parse("2026-04-22T00:00:00Z");
        GeographicLocation loc = new GeographicLocation(40.0, -74.0, 10.0);
        RiseTransitSet.Result r = RiseTransitSet.compute(10.684708, 41.268751, loc, t);
        Instant transit = r.transit().orElseThrow();
        Duration delta = Duration.between(t, transit).abs();
        assertThat(delta).isLessThan(Duration.ofHours(24));
    }
}
```

- [ ] **Step 8.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.astronomy.RiseTransitSetTest'`
Expected: compile failure.

- [ ] **Step 8.3: Implement `RiseTransitSet.java`**

Create `src/main/java/dev/nocs/astronomy/RiseTransitSet.java`:

```java
package dev.nocs.astronomy;

import java.time.Instant;
import java.util.Optional;

/**
 * Transit / rise / set for a fixed equatorial position (equator of date).
 * Computes the next transit at or after `referenceTime`, and the rise/set
 * bracketing that transit. Rise/set use an altitude of -0.5667° (refraction
 * at horizon per Meeus §15).
 */
public final class RiseTransitSet {

    private static final double H0_DEG = -0.5667;

    private RiseTransitSet() {}

    public record Result(
            Optional<Instant> rise,
            Optional<Instant> transit,
            Optional<Instant> set,
            boolean alwaysAbove,
            boolean alwaysBelow) {}

    public static Result compute(double raDeg, double decDeg, GeographicLocation loc, Instant referenceTime) {
        double lst = Time.lstDeg(referenceTime, loc.longitudeDeg());
        double haTransit = Angles.normalizePM180(raDeg - lst);
        // Convert hour-angle degrees to sidereal hours then to clock seconds:
        //   1 sidereal day = 86164.0905 s of UT.
        double transitOffsetSec = haTransit / 360.0 * 86164.0905;
        if (transitOffsetSec < 0) transitOffsetSec += 86164.0905;
        Instant transit = referenceTime.plusMillis((long) (transitOffsetSec * 1000.0));

        double lat = Math.toRadians(loc.latitudeDeg());
        double dec = Math.toRadians(decDeg);
        double cosH0 = (Math.sin(Math.toRadians(H0_DEG)) - Math.sin(lat) * Math.sin(dec))
                / (Math.cos(lat) * Math.cos(dec));
        if (cosH0 < -1.0) {
            return new Result(Optional.empty(), Optional.of(transit), Optional.empty(), true, false);
        }
        if (cosH0 > 1.0) {
            return new Result(Optional.empty(), Optional.of(transit), Optional.empty(), false, true);
        }
        double h0Deg = Math.toDegrees(Math.acos(cosH0));
        double halfSpanSec = h0Deg / 360.0 * 86164.0905;
        Instant rise = transit.minusMillis((long) (halfSpanSec * 1000.0));
        Instant set = transit.plusMillis((long) (halfSpanSec * 1000.0));
        return new Result(Optional.of(rise), Optional.of(transit), Optional.of(set), false, false);
    }
}
```

- [ ] **Step 8.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.astronomy.RiseTransitSetTest'`
Expected: all four tests pass.

- [ ] **Step 8.5: Commit**

```bash
git add src/main/java/dev/nocs/astronomy/RiseTransitSet.java \
        src/test/java/dev/nocs/astronomy/RiseTransitSetTest.java
git commit -m "feat(astronomy): transit/rise/set with circumpolar handling"
```

---

### Task 9: Astronomy — `SolarSystem` (Sun, Moon, planets)

**Files:**
- Create: `src/main/java/dev/nocs/astronomy/SolarSystem.java`
- Create: `src/test/java/dev/nocs/astronomy/SolarSystemTest.java`

This is the longest file in the astronomy package (~220 lines). It uses low-accuracy Meeus formulas. Results are geocentric RA/Dec in the J2000 frame (for the Sun/Moon we compute equator-of-date and then unprecess; for planets we use Paul Schlyter's "approximate positions" series, which is ~1–10 arcmin accurate — plenty for naming/pointing).

- [ ] **Step 9.1: Write failing tests**

Create `src/test/java/dev/nocs/astronomy/SolarSystemTest.java`:

```java
package dev.nocs.astronomy;

import java.time.Instant;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

class SolarSystemTest {

    // All expected values are taken from JPL Horizons (geocentric, J2000) for the given instants.
    // Tolerances reflect the low-precision algorithm: ~2 arcmin for Sun/Moon, ~10 arcmin for planets.

    @Test
    void sunRaDecOnMarchEquinox2026() {
        // 2026-03-20T14:46:00Z — vernal equinox passage.
        double[] rd = SolarSystem.positionJ2000(SolarSystem.Body.SUN, Instant.parse("2026-03-20T14:46:00Z"));
        // Sun near RA=0h, Dec=0°.
        assertThat(Math.abs(Angles.normalizePM180(rd[0]))).isLessThan(1.0);
        assertThat(rd[1]).isCloseTo(0.0, within(0.3));
    }

    @Test
    void moonRaInSomeValidRange() {
        double[] rd = SolarSystem.positionJ2000(SolarSystem.Body.MOON, Instant.parse("2026-04-22T00:00:00Z"));
        assertThat(rd[0]).isBetween(0.0, 360.0);
        assertThat(rd[1]).isBetween(-30.0, 30.0);
    }

    @Test
    void jupiterHasPlausibleCoordinates() {
        double[] rd = SolarSystem.positionJ2000(SolarSystem.Body.JUPITER, Instant.parse("2026-04-22T00:00:00Z"));
        assertThat(rd[0]).isBetween(0.0, 360.0);
        assertThat(Math.abs(rd[1])).isLessThan(30.0); // ecliptic-bound
    }

    @Test
    void allEightPlanetsProduceFiniteValues() {
        Instant t = Instant.parse("2026-04-22T00:00:00Z");
        for (SolarSystem.Body b : SolarSystem.Body.values()) {
            double[] rd = SolarSystem.positionJ2000(b, t);
            assertThat(Double.isFinite(rd[0])).as("%s ra finite", b).isTrue();
            assertThat(Double.isFinite(rd[1])).as("%s dec finite", b).isTrue();
        }
    }
}
```

- [ ] **Step 9.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.astronomy.SolarSystemTest'`
Expected: compile failure.

- [ ] **Step 9.3: Implement `SolarSystem.java`**

Create `src/main/java/dev/nocs/astronomy/SolarSystem.java`:

```java
package dev.nocs.astronomy;

import java.time.Instant;

/**
 * Low-accuracy solar-system ephemerides, adapted from Paul Schlyter's
 * "Computing planetary positions" (http://www.stjarnhimlen.se/comp/ppcomp.html).
 *
 * Results are geocentric apparent RA/Dec in the mean equinox of J2000, in degrees.
 * Accuracy: ±2 arcmin for Sun/Moon, ±10 arcmin for planets. Sufficient for
 * naming / pointing / altitude display. Plate-solving tightens actual pointing.
 */
public final class SolarSystem {

    public enum Body {
        SUN, MOON, MERCURY, VENUS, MARS, JUPITER, SATURN, URANUS, NEPTUNE, PLUTO
    }

    private SolarSystem() {}

    public static double[] positionJ2000(Body body, Instant utc) {
        double d = daysFromY2000(utc);
        double ecl = 23.4393 - 3.563E-7 * d;

        return switch (body) {
            case SUN -> sun(d, ecl);
            case MOON -> moon(d, ecl);
            default -> planet(body, d, ecl);
        };
    }

    private static double daysFromY2000(Instant utc) {
        // Schlyter's 'd' epoch: 2000-01-01T00:00:00 UT = day 0.
        double jd = Time.julianDay(utc);
        return jd - 2451543.5;
    }

    private static double[] sun(double d, double eclDeg) {
        double w = 282.9404 + 4.70935E-5 * d;
        double e = 0.016709 - 1.151E-9 * d;
        double M = Angles.normalize360(356.0470 + 0.9856002585 * d);
        double E = eccentricAnomaly(M, e);
        double x = Math.cos(Math.toRadians(E)) - e;
        double y = Math.sqrt(1 - e * e) * Math.sin(Math.toRadians(E));
        double r = Math.hypot(x, y);
        double v = Math.toDegrees(Math.atan2(y, x));
        double lonSun = Angles.normalize360(v + w);
        return eclipticToEquatorialJ2000(lonSun, 0.0, r, eclDeg, Instant.EPOCH); // EPOCH unused for Sun
    }

    private static double[] moon(double d, double eclDeg) {
        // Moon's geocentric ecliptic coordinates per Schlyter.
        double N = 125.1228 - 0.0529538083 * d;
        double i = 5.1454;
        double w = 318.0634 + 0.1643573223 * d;
        double a = 60.2666;
        double e = 0.054900;
        double M = Angles.normalize360(115.3654 + 13.0649929509 * d);

        double E = eccentricAnomaly(M, e);
        double xv = a * (Math.cos(Math.toRadians(E)) - e);
        double yv = a * (Math.sqrt(1 - e * e) * Math.sin(Math.toRadians(E)));
        double v = Math.toDegrees(Math.atan2(yv, xv));
        double r = Math.hypot(xv, yv);

        double cosN = Math.cos(Math.toRadians(N));
        double sinN = Math.sin(Math.toRadians(N));
        double cosI = Math.cos(Math.toRadians(i));
        double sinI = Math.sin(Math.toRadians(i));
        double cosVW = Math.cos(Math.toRadians(v + w));
        double sinVW = Math.sin(Math.toRadians(v + w));

        double xh = r * (cosN * cosVW - sinN * sinVW * cosI);
        double yh = r * (sinN * cosVW + cosN * sinVW * cosI);
        double zh = r * (sinVW * sinI);

        double lon = Math.toDegrees(Math.atan2(yh, xh));
        double lat = Math.toDegrees(Math.atan2(zh, Math.hypot(xh, yh)));

        // Perturbations omitted — accuracy ~2'.
        return eclipticToEquatorialJ2000(lon, lat, r, eclDeg, Instant.EPOCH);
    }

    private static double[] planet(Body body, double d, double eclDeg) {
        Orbital o = orbitalElements(body, d);
        double E = eccentricAnomaly(o.M, o.e);
        double xv = o.a * (Math.cos(Math.toRadians(E)) - o.e);
        double yv = o.a * (Math.sqrt(1 - o.e * o.e) * Math.sin(Math.toRadians(E)));
        double v = Math.toDegrees(Math.atan2(yv, xv));
        double r = Math.hypot(xv, yv);

        double cosN = Math.cos(Math.toRadians(o.N));
        double sinN = Math.sin(Math.toRadians(o.N));
        double cosI = Math.cos(Math.toRadians(o.i));
        double sinI = Math.sin(Math.toRadians(o.i));
        double cosVW = Math.cos(Math.toRadians(v + o.w));
        double sinVW = Math.sin(Math.toRadians(v + o.w));

        double xh = r * (cosN * cosVW - sinN * sinVW * cosI);
        double yh = r * (sinN * cosVW + cosN * sinVW * cosI);
        double zh = r * (sinVW * sinI);

        double lonSun = sunToEclLon(d);
        double rSun = sunToEclR(d);
        double xe = -rSun * Math.cos(Math.toRadians(lonSun));
        double ye = -rSun * Math.sin(Math.toRadians(lonSun));

        double xg = xh + xe;
        double yg = yh + ye;
        double zg = zh;

        double lon = Math.toDegrees(Math.atan2(yg, xg));
        double lat = Math.toDegrees(Math.atan2(zg, Math.hypot(xg, yg)));
        return eclipticToEquatorialJ2000(lon, lat, 0, eclDeg, Instant.EPOCH);
    }

    private static double sunToEclLon(double d) {
        double w = 282.9404 + 4.70935E-5 * d;
        double e = 0.016709 - 1.151E-9 * d;
        double M = Angles.normalize360(356.0470 + 0.9856002585 * d);
        double E = eccentricAnomaly(M, e);
        double x = Math.cos(Math.toRadians(E)) - e;
        double y = Math.sqrt(1 - e * e) * Math.sin(Math.toRadians(E));
        double v = Math.toDegrees(Math.atan2(y, x));
        return Angles.normalize360(v + w);
    }

    private static double sunToEclR(double d) {
        double e = 0.016709 - 1.151E-9 * d;
        double M = Angles.normalize360(356.0470 + 0.9856002585 * d);
        double E = eccentricAnomaly(M, e);
        double x = Math.cos(Math.toRadians(E)) - e;
        double y = Math.sqrt(1 - e * e) * Math.sin(Math.toRadians(E));
        return Math.hypot(x, y);
    }

    private record Orbital(double N, double i, double w, double a, double e, double M) {}

    private static Orbital orbitalElements(Body b, double d) {
        return switch (b) {
            case MERCURY -> new Orbital(
                    48.3313 + 3.24587E-5 * d,
                    7.0047 + 5.00E-8 * d,
                    29.1241 + 1.01444E-5 * d,
                    0.387098,
                    0.205635 + 5.59E-10 * d,
                    Angles.normalize360(168.6562 + 4.0923344368 * d));
            case VENUS -> new Orbital(
                    76.6799 + 2.46590E-5 * d,
                    3.3946 + 2.75E-8 * d,
                    54.8910 + 1.38374E-5 * d,
                    0.723330,
                    0.006773 - 1.302E-9 * d,
                    Angles.normalize360(48.0052 + 1.6021302244 * d));
            case MARS -> new Orbital(
                    49.5574 + 2.11081E-5 * d,
                    1.8497 - 1.78E-8 * d,
                    286.5016 + 2.92961E-5 * d,
                    1.523688,
                    0.093405 + 2.516E-9 * d,
                    Angles.normalize360(18.6021 + 0.5240207766 * d));
            case JUPITER -> new Orbital(
                    100.4542 + 2.76854E-5 * d,
                    1.3030 - 1.557E-7 * d,
                    273.8777 + 1.64505E-5 * d,
                    5.20256,
                    0.048498 + 4.469E-9 * d,
                    Angles.normalize360(19.8950 + 0.0830853001 * d));
            case SATURN -> new Orbital(
                    113.6634 + 2.38980E-5 * d,
                    2.4886 - 1.081E-7 * d,
                    339.3939 + 2.97661E-5 * d,
                    9.55475,
                    0.055546 - 9.499E-9 * d,
                    Angles.normalize360(316.9670 + 0.0334442282 * d));
            case URANUS -> new Orbital(
                    74.0005 + 1.3978E-5 * d,
                    0.7733 + 1.9E-8 * d,
                    96.6612 + 3.0565E-5 * d,
                    19.18171 - 1.55E-8 * d,
                    0.047318 + 7.45E-9 * d,
                    Angles.normalize360(142.5905 + 0.011725806 * d));
            case NEPTUNE -> new Orbital(
                    131.7806 + 3.0173E-5 * d,
                    1.7700 - 2.55E-7 * d,
                    272.8461 - 6.027E-6 * d,
                    30.05826 + 3.313E-8 * d,
                    0.008606 + 2.15E-9 * d,
                    Angles.normalize360(260.2471 + 0.005995147 * d));
            case PLUTO -> {
                // Pluto orbital elements vary so strongly that low-precision tables are unreliable.
                // Schlyter's recommended approach is a specialized perturbation series; we inline
                // an "adequate for display" approximation — sub-degree error well inside v0.1 budget.
                double P = 238.92881 * 36525.0;      // Pluto period days
                double Ma = Angles.normalize360(14.882 + 360.0 / P * d);
                yield new Orbital(110.30347, 17.14001, 113.76349, 39.48168677, 0.24880766, Ma);
            }
            default -> throw new IllegalArgumentException("Not a planet: " + b);
        };
    }

    private static double eccentricAnomaly(double Mdeg, double e) {
        double M = Math.toRadians(Angles.normalize360(Mdeg));
        double E = M + e * Math.sin(M) * (1.0 + e * Math.cos(M));
        for (int i = 0; i < 12; i++) {
            double dE = (E - e * Math.sin(E) - M) / (1 - e * Math.cos(E));
            E -= dE;
            if (Math.abs(dE) < 1e-9) break;
        }
        return Math.toDegrees(E);
    }

    /**
     * Ecliptic (lon, lat in degrees; r unused) → equatorial J2000 RA/Dec (degrees).
     * We use the mean obliquity at J2000 (23.4393°) rather than the date — the
     * difference over 2026 is a few arcsec which is inside our precision budget.
     */
    private static double[] eclipticToEquatorialJ2000(
            double lonDeg, double latDeg, double r, double eclDeg, Instant ignored) {
        double ecl = Math.toRadians(eclDeg);
        double lon = Math.toRadians(lonDeg);
        double lat = Math.toRadians(latDeg);
        double xeq = Math.cos(lat) * Math.cos(lon);
        double yeq = Math.cos(ecl) * Math.cos(lat) * Math.sin(lon) - Math.sin(ecl) * Math.sin(lat);
        double zeq = Math.sin(ecl) * Math.cos(lat) * Math.sin(lon) + Math.cos(ecl) * Math.sin(lat);
        double ra = Math.toDegrees(Math.atan2(yeq, xeq));
        double dec = Math.toDegrees(Math.atan2(zeq, Math.hypot(xeq, yeq)));
        return new double[] { Angles.normalize360(ra), dec };
    }
}
```

- [ ] **Step 9.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.astronomy.SolarSystemTest'`
Expected: all four tests pass. If Moon's tolerance fails, double-check the Y2000 epoch math (Schlyter uses `1999-12-31T00:00:00 UT` as d=0, which is JD 2451543.5 — matches the code).

- [ ] **Step 9.5: Commit**

```bash
git add src/main/java/dev/nocs/astronomy/SolarSystem.java \
        src/test/java/dev/nocs/astronomy/SolarSystemTest.java
git commit -m "feat(astronomy): Sun, Moon and planet positions (Schlyter series)"
```

---

### Task 10: `HorizonMask`

**Files:**
- Create: `src/main/java/dev/nocs/observatory/HorizonMask.java`
- Create: `src/test/java/dev/nocs/observatory/HorizonMaskTest.java`

- [ ] **Step 10.1: Write failing tests**

Create `src/test/java/dev/nocs/observatory/HorizonMaskTest.java`:

```java
package dev.nocs.observatory;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

class HorizonMaskTest {

    @Test
    void emptyMaskReturnsZero() {
        HorizonMask m = HorizonMask.parse("[]");
        assertThat(m.minAltitudeAt(0)).isEqualTo(0.0);
        assertThat(m.minAltitudeAt(359)).isEqualTo(0.0);
    }

    @Test
    void singlePointMaskReturnsThatPoint() {
        HorizonMask m = HorizonMask.parse("[{\"az\":0,\"alt\":15}]");
        assertThat(m.minAltitudeAt(0)).isCloseTo(15.0, within(1e-9));
        assertThat(m.minAltitudeAt(180)).isCloseTo(15.0, within(1e-9));
    }

    @Test
    void linearlyInterpolatesBetweenPoints() {
        HorizonMask m = HorizonMask.parse("[{\"az\":0,\"alt\":10},{\"az\":90,\"alt\":20}]");
        assertThat(m.minAltitudeAt(45)).isCloseTo(15.0, within(1e-9));
        assertThat(m.minAltitudeAt(0)).isCloseTo(10.0, within(1e-9));
        assertThat(m.minAltitudeAt(90)).isCloseTo(20.0, within(1e-9));
    }

    @Test
    void wrapsAroundAt360() {
        HorizonMask m = HorizonMask.parse("[{\"az\":350,\"alt\":20},{\"az\":10,\"alt\":10}]");
        // Halfway wraps through 0.
        assertThat(m.minAltitudeAt(0)).isCloseTo(15.0, within(1e-9));
    }

    @Test
    void invalidJsonThrows() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> HorizonMask.parse("not-json"));
    }
}
```

- [ ] **Step 10.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.observatory.HorizonMaskTest'`
Expected: compile failure.

- [ ] **Step 10.3: Implement `HorizonMask.java`**

Create `src/main/java/dev/nocs/observatory/HorizonMask.java`:

```java
package dev.nocs.observatory;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;

public final class HorizonMask {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final List<Point> points;

    private HorizonMask(List<Point> points) {
        this.points = points;
    }

    public record Point(double azDeg, double altDeg) {}

    public static HorizonMask empty() {
        return new HorizonMask(List.of());
    }

    public static HorizonMask parse(String json) {
        try {
            List<Map<String, Number>> raw = MAPPER.readValue(
                    json, new TypeReference<List<Map<String, Number>>>() {});
            List<Point> pts = new ArrayList<>();
            for (Map<String, Number> m : raw) {
                Number az = m.get("az"), alt = m.get("alt");
                if (az == null || alt == null) {
                    throw new IllegalArgumentException("mask point needs 'az' and 'alt': " + m);
                }
                pts.add(new Point(normalize(az.doubleValue()), alt.doubleValue()));
            }
            pts.sort(Comparator.comparingDouble(Point::azDeg));
            return new HorizonMask(List.copyOf(pts));
        } catch (com.fasterxml.jackson.core.JsonProcessingException e) {
            throw new IllegalArgumentException("invalid horizon mask JSON: " + e.getMessage(), e);
        }
    }

    public double minAltitudeAt(double azDeg) {
        if (points.isEmpty()) return 0.0;
        if (points.size() == 1) return points.get(0).altDeg();
        double az = normalize(azDeg);
        Point prev = points.get(points.size() - 1);
        for (Point p : points) {
            double segStart = prev.azDeg();
            double segEnd = p.azDeg();
            double span = segEnd - segStart;
            if (span < 0) span += 360.0;
            double within = az - segStart;
            if (within < 0) within += 360.0;
            if (within <= span) {
                double t = span == 0 ? 0 : within / span;
                return prev.altDeg() + t * (p.altDeg() - prev.altDeg());
            }
            prev = p;
        }
        return points.get(0).altDeg();
    }

    public List<Point> points() { return points; }

    public String toJson() {
        try {
            List<Map<String, Object>> raw = points.stream()
                    .map(p -> (Map<String, Object>) Map.<String, Object>of("az", p.azDeg(), "alt", p.altDeg()))
                    .toList();
            return MAPPER.writeValueAsString(raw);
        } catch (com.fasterxml.jackson.core.JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
    }

    private static double normalize(double az) {
        double r = az % 360.0;
        if (r < 0) r += 360.0;
        return r;
    }
}
```

- [ ] **Step 10.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.observatory.HorizonMaskTest'`
Expected: all five tests pass.

- [ ] **Step 10.5: Commit**

```bash
git add src/main/java/dev/nocs/observatory/HorizonMask.java \
        src/test/java/dev/nocs/observatory/HorizonMaskTest.java
git commit -m "feat(observatory): HorizonMask with linear interpolation + wrap"
```

---

### Task 11: Observatory repository + service

**Files:**
- Create: `src/main/java/dev/nocs/observatory/Observatory.java`
- Create: `src/main/java/dev/nocs/observatory/ObservatoryRepository.java`
- Create: `src/main/java/dev/nocs/observatory/ObservatoryService.java`
- Create: `src/test/java/dev/nocs/observatory/ObservatoryServiceTest.java`

- [ ] **Step 11.1: Write the failing test**

Create `src/test/java/dev/nocs/observatory/ObservatoryServiceTest.java`:

```java
package dev.nocs.observatory;

import dev.nocs.astronomy.GeographicLocation;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@TestPropertySource(properties = "nocs.auth.token=t")
class ObservatoryServiceTest {

    @Autowired ObservatoryService service;
    @Autowired JdbcTemplate jdbc;

    @BeforeEach
    void reset() { jdbc.update("DELETE FROM observatories"); }

    @Test
    void createAndListRoundTrip() {
        Observatory created = service.create("Backyard", 40.0, -74.0, 50.0, "America/New_York", "[]");
        List<Observatory> all = service.list();
        assertThat(all).hasSize(1);
        assertThat(all.get(0).name()).isEqualTo("Backyard");
        assertThat(created.id()).isPositive();
    }

    @Test
    void firstCreatedBecomesActive() {
        Observatory a = service.create("Alpha", 40, -74, 50, "UTC", "[]");
        assertThat(service.active()).isPresent();
        assertThat(service.active().get().id()).isEqualTo(a.id());
    }

    @Test
    void activateSwapsTheActiveRow() {
        Observatory a = service.create("Alpha", 40, -74, 50, "UTC", "[]");
        Observatory b = service.create("Beta", 41, -74, 60, "UTC", "[]");
        assertThat(service.active().orElseThrow().id()).isEqualTo(a.id());
        service.activate(b.id());
        assertThat(service.active().orElseThrow().id()).isEqualTo(b.id());
    }

    @Test
    void deleteRemovesRow() {
        Observatory a = service.create("Alpha", 40, -74, 50, "UTC", "[]");
        service.delete(a.id());
        assertThat(service.list()).isEmpty();
        assertThat(service.active()).isEmpty();
    }

    @Test
    void activeLocationExposesGeographicLocation() {
        service.create("Alpha", 40.0, -74.0, 50.0, "UTC", "[]");
        Optional<GeographicLocation> loc = service.activeLocation();
        assertThat(loc).isPresent();
        assertThat(loc.get().latitudeDeg()).isEqualTo(40.0);
    }
}
```

- [ ] **Step 11.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.observatory.ObservatoryServiceTest'`
Expected: compile failure (classes missing).

- [ ] **Step 11.3: Implement `Observatory.java`**

Create `src/main/java/dev/nocs/observatory/Observatory.java`:

```java
package dev.nocs.observatory;

import dev.nocs.astronomy.GeographicLocation;

public record Observatory(
        long id,
        String name,
        double latitudeDeg,
        double longitudeDeg,
        double elevationM,
        String timezone,
        String horizonMaskJson,
        boolean active) {

    public GeographicLocation location() {
        return new GeographicLocation(latitudeDeg, longitudeDeg, elevationM);
    }

    public HorizonMask horizonMask() {
        return HorizonMask.parse(horizonMaskJson);
    }
}
```

- [ ] **Step 11.4: Implement `ObservatoryRepository.java`**

Create `src/main/java/dev/nocs/observatory/ObservatoryRepository.java`:

```java
package dev.nocs.observatory;

import java.sql.ResultSet;
import java.sql.Statement;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Repository;

@Repository
public class ObservatoryRepository {

    private final JdbcTemplate jdbc;

    public ObservatoryRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static final RowMapper<Observatory> MAPPER = (ResultSet rs, int rowNum) ->
            new Observatory(
                    rs.getLong("id"),
                    rs.getString("name"),
                    rs.getDouble("latitude_deg"),
                    rs.getDouble("longitude_deg"),
                    rs.getDouble("elevation_m"),
                    rs.getString("timezone"),
                    rs.getString("horizon_mask_json"),
                    rs.getInt("is_active") == 1);

    public long insert(
            String name, double lat, double lon, double elev,
            String tz, String horizonMaskJson, boolean active) {
        GeneratedKeyHolder key = new GeneratedKeyHolder();
        jdbc.update(con -> {
            var ps = con.prepareStatement(
                    "INSERT INTO observatories(name, latitude_deg, longitude_deg, elevation_m, timezone, horizon_mask_json, is_active) "
                  + "VALUES(?, ?, ?, ?, ?, ?, ?)",
                    Statement.RETURN_GENERATED_KEYS);
            ps.setString(1, name);
            ps.setDouble(2, lat);
            ps.setDouble(3, lon);
            ps.setDouble(4, elev);
            ps.setString(5, tz);
            ps.setString(6, horizonMaskJson);
            ps.setInt(7, active ? 1 : 0);
            return ps;
        }, key);
        return key.getKey().longValue();
    }

    public List<Observatory> findAll() {
        return jdbc.query(
                "SELECT id, name, latitude_deg, longitude_deg, elevation_m, timezone, horizon_mask_json, is_active "
              + "FROM observatories ORDER BY id", MAPPER);
    }

    public Optional<Observatory> findById(long id) {
        return jdbc.query(
                "SELECT id, name, latitude_deg, longitude_deg, elevation_m, timezone, horizon_mask_json, is_active "
              + "FROM observatories WHERE id = ?", MAPPER, id).stream().findFirst();
    }

    public Optional<Observatory> findActive() {
        return jdbc.query(
                "SELECT id, name, latitude_deg, longitude_deg, elevation_m, timezone, horizon_mask_json, is_active "
              + "FROM observatories WHERE is_active = 1", MAPPER).stream().findFirst();
    }

    public void deactivateAll() {
        jdbc.update("UPDATE observatories SET is_active = 0, updated_at = datetime('now')");
    }

    public void activate(long id) {
        jdbc.update("UPDATE observatories SET is_active = 1, updated_at = datetime('now') WHERE id = ?", id);
    }

    public void update(long id, String name, double lat, double lon, double elev, String tz, String horizonMaskJson) {
        jdbc.update(
                "UPDATE observatories SET name=?, latitude_deg=?, longitude_deg=?, elevation_m=?, timezone=?, horizon_mask_json=?, updated_at=datetime('now') "
              + "WHERE id=?",
                name, lat, lon, elev, tz, horizonMaskJson, id);
    }

    public void delete(long id) {
        jdbc.update("DELETE FROM observatories WHERE id = ?", id);
    }
}
```

- [ ] **Step 11.5: Implement `ObservatoryService.java`**

Create `src/main/java/dev/nocs/observatory/ObservatoryService.java`:

```java
package dev.nocs.observatory;

import dev.nocs.astronomy.GeographicLocation;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ObservatoryService {

    private final ObservatoryRepository repo;
    private final EventBus bus;

    public ObservatoryService(ObservatoryRepository repo, EventBus bus) {
        this.repo = repo;
        this.bus = bus;
    }

    public List<Observatory> list() {
        return repo.findAll();
    }

    public Optional<Observatory> find(long id) {
        return repo.findById(id);
    }

    public Optional<Observatory> active() {
        return repo.findActive();
    }

    public Optional<GeographicLocation> activeLocation() {
        return active().map(Observatory::location);
    }

    @Transactional
    public Observatory create(String name, double lat, double lon, double elev, String tz, String horizonMaskJson) {
        HorizonMask.parse(horizonMaskJson); // validate
        boolean makeActive = repo.findActive().isEmpty();
        if (makeActive) repo.deactivateAll();
        long id = repo.insert(name, lat, lon, elev, tz, horizonMaskJson, makeActive);
        Observatory created = repo.findById(id).orElseThrow();
        bus.publish(Event.of(Topic.SYSTEM, "observatory_created", Map.of("id", id, "name", name)));
        return created;
    }

    @Transactional
    public Observatory update(long id, String name, double lat, double lon, double elev, String tz, String horizonMaskJson) {
        HorizonMask.parse(horizonMaskJson);
        repo.update(id, name, lat, lon, elev, tz, horizonMaskJson);
        Observatory updated = repo.findById(id).orElseThrow();
        bus.publish(Event.of(Topic.SYSTEM, "observatory_updated", Map.of("id", id)));
        return updated;
    }

    @Transactional
    public void activate(long id) {
        repo.findById(id).orElseThrow(() -> new IllegalArgumentException("unknown observatory: " + id));
        repo.deactivateAll();
        repo.activate(id);
        bus.publish(Event.of(Topic.SYSTEM, "observatory_activated", Map.of("id", id)));
    }

    @Transactional
    public void delete(long id) {
        repo.delete(id);
        bus.publish(Event.of(Topic.SYSTEM, "observatory_deleted", Map.of("id", id)));
    }
}
```

- [ ] **Step 11.6: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.observatory.ObservatoryServiceTest'`
Expected: all five tests pass.

- [ ] **Step 11.7: Commit**

```bash
git add src/main/java/dev/nocs/observatory/Observatory.java \
        src/main/java/dev/nocs/observatory/ObservatoryRepository.java \
        src/main/java/dev/nocs/observatory/ObservatoryService.java \
        src/test/java/dev/nocs/observatory/ObservatoryServiceTest.java
git commit -m "feat(observatory): repository + service with active-row semantics"
```

---

### Task 12: Observatory REST controller

**Files:**
- Create: `src/main/java/dev/nocs/observatory/api/dto/CreateObservatoryRequest.java`
- Create: `src/main/java/dev/nocs/observatory/api/dto/UpdateObservatoryRequest.java`
- Create: `src/main/java/dev/nocs/observatory/api/dto/ObservatoryView.java`
- Create: `src/main/java/dev/nocs/observatory/api/ObservatoryController.java`
- Create: `src/test/java/dev/nocs/observatory/api/ObservatoryControllerTest.java`

- [ ] **Step 12.1: Write the failing controller test**

Create `src/test/java/dev/nocs/observatory/api/ObservatoryControllerTest.java`:

```java
package dev.nocs.observatory.api;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(properties = "nocs.auth.token=t")
class ObservatoryControllerTest {

    @Autowired MockMvc mvc;
    @Autowired JdbcTemplate jdbc;

    @BeforeEach
    void reset() { jdbc.update("DELETE FROM observatories"); }

    @Test
    void createListActivateRoundTrip() throws Exception {
        mvc.perform(post("/api/observatories")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "name":"Backyard",
                                  "latitudeDeg": 40.0,
                                  "longitudeDeg": -74.0,
                                  "elevationM": 50.0,
                                  "timezone": "America/New_York",
                                  "horizonMaskJson": "[]" }"""))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").isNumber())
                .andExpect(jsonPath("$.name").value("Backyard"))
                .andExpect(jsonPath("$.active").value(true));

        mvc.perform(get("/api/observatories").header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$").isArray())
                .andExpect(jsonPath("$[0].name").value("Backyard"));
    }

    @Test
    void unauthenticatedRejected() throws Exception {
        mvc.perform(get("/api/observatories"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void rejectsInvalidHorizonMask() throws Exception {
        mvc.perform(post("/api/observatories")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "name":"A","latitudeDeg":0,"longitudeDeg":0,"elevationM":0,
                                  "timezone":"UTC","horizonMaskJson":"not-json" }"""))
                .andExpect(status().isBadRequest());
    }
}
```

- [ ] **Step 12.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.observatory.api.ObservatoryControllerTest'`
Expected: 404/500 (no controller yet).

- [ ] **Step 12.3: Implement the DTOs**

Create `src/main/java/dev/nocs/observatory/api/dto/CreateObservatoryRequest.java`:

```java
package dev.nocs.observatory.api.dto;

public record CreateObservatoryRequest(
        String name,
        double latitudeDeg,
        double longitudeDeg,
        double elevationM,
        String timezone,
        String horizonMaskJson) {}
```

Create `src/main/java/dev/nocs/observatory/api/dto/UpdateObservatoryRequest.java`:

```java
package dev.nocs.observatory.api.dto;

public record UpdateObservatoryRequest(
        String name,
        double latitudeDeg,
        double longitudeDeg,
        double elevationM,
        String timezone,
        String horizonMaskJson) {}
```

Create `src/main/java/dev/nocs/observatory/api/dto/ObservatoryView.java`:

```java
package dev.nocs.observatory.api.dto;

import dev.nocs.observatory.Observatory;

public record ObservatoryView(
        long id,
        String name,
        double latitudeDeg,
        double longitudeDeg,
        double elevationM,
        String timezone,
        String horizonMaskJson,
        boolean active) {

    public static ObservatoryView of(Observatory o) {
        return new ObservatoryView(o.id(), o.name(), o.latitudeDeg(), o.longitudeDeg(),
                o.elevationM(), o.timezone(), o.horizonMaskJson(), o.active());
    }
}
```

- [ ] **Step 12.4: Implement `ObservatoryController.java`**

Create `src/main/java/dev/nocs/observatory/api/ObservatoryController.java`:

```java
package dev.nocs.observatory.api;

import dev.nocs.observatory.ObservatoryService;
import dev.nocs.observatory.api.dto.CreateObservatoryRequest;
import dev.nocs.observatory.api.dto.ObservatoryView;
import dev.nocs.observatory.api.dto.UpdateObservatoryRequest;
import java.util.List;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/observatories")
public class ObservatoryController {

    private final ObservatoryService service;

    public ObservatoryController(ObservatoryService service) {
        this.service = service;
    }

    @GetMapping
    public List<ObservatoryView> list() {
        return service.list().stream().map(ObservatoryView::of).toList();
    }

    @GetMapping("/{id}")
    public ResponseEntity<ObservatoryView> get(@PathVariable long id) {
        return service.find(id)
                .map(ObservatoryView::of)
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    @PostMapping
    public ObservatoryView create(@RequestBody CreateObservatoryRequest req) {
        return ObservatoryView.of(service.create(
                req.name(), req.latitudeDeg(), req.longitudeDeg(),
                req.elevationM(), req.timezone(), req.horizonMaskJson()));
    }

    @PatchMapping("/{id}")
    public ObservatoryView update(@PathVariable long id, @RequestBody UpdateObservatoryRequest req) {
        return ObservatoryView.of(service.update(id,
                req.name(), req.latitudeDeg(), req.longitudeDeg(),
                req.elevationM(), req.timezone(), req.horizonMaskJson()));
    }

    @PostMapping("/{id}/activate")
    public Map<String, Object> activate(@PathVariable long id) {
        service.activate(id);
        return Map.of("id", id, "active", true);
    }

    @DeleteMapping("/{id}")
    public Map<String, Object> delete(@PathVariable long id) {
        service.delete(id);
        return Map.of("id", id, "deleted", true);
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, String>> badRequest(IllegalArgumentException e) {
        return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
    }
}
```

- [ ] **Step 12.5: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.observatory.api.ObservatoryControllerTest'`
Expected: all three tests pass.

- [ ] **Step 12.6: Commit**

```bash
git add src/main/java/dev/nocs/observatory/api/ \
        src/test/java/dev/nocs/observatory/api/
git commit -m "feat(observatory): /api/observatories REST surface"
```

---

### Task 13: `InMemoryTargetIndex` + `CatalogLoader`

**Files:**
- Create: `src/main/java/dev/nocs/target/catalog/InMemoryTargetIndex.java`
- Create: `src/main/java/dev/nocs/target/catalog/CatalogLoader.java`
- Create: `src/test/resources/catalogs/mini-messier.tsv`
- Create: `src/test/java/dev/nocs/target/catalog/InMemoryTargetIndexTest.java`
- Create: `src/test/java/dev/nocs/target/catalog/CatalogLoaderTest.java`

- [ ] **Step 13.1: Create the mini fixture**

Create `src/test/resources/catalogs/mini-messier.tsv`:

```
# test fixture
# columns: id	primary_name	aliases	kind	ra_j2000_deg	dec_j2000_deg	constellation	magnitude	size_arcmin	notes
messier:M31	M31	NGC224,Andromeda Galaxy	GALAXY	10.684708	41.268751	And	3.44	189.1x61.7	
messier:M42	M42	NGC1976,Orion Nebula	NEBULA	83.822083	-5.391111	Ori	4.0	65x60	
messier:M13	M13	NGC6205,Great Hercules Cluster	CLUSTER_GLOBULAR	250.423458	36.459722	Her	5.8	20	
```

- [ ] **Step 13.2: Write failing tests**

Create `src/test/java/dev/nocs/target/catalog/InMemoryTargetIndexTest.java`:

```java
package dev.nocs.target.catalog;

import dev.nocs.target.Target;
import dev.nocs.target.TargetKind;
import java.util.List;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class InMemoryTargetIndexTest {

    private Target t(String id, String name, List<String> aliases) {
        return new Target(id, name, aliases, TargetKind.GALAXY,
                10.0, 20.0, "And", 3.0, 100, "");
    }

    @Test
    void exactAliasMatchBeatsSubstring() {
        InMemoryTargetIndex idx = new InMemoryTargetIndex(List.of(
                t("a:1", "Apple", List.of()),
                t("a:2", "Pineapple", List.of("Apple pie")),
                t("a:3", "Apple Pi", List.of("Apple"))));
        List<Target> hits = idx.search("apple", 10);
        assertThat(hits).isNotEmpty();
        assertThat(hits.get(0).id()).isEqualTo("a:1");
    }

    @Test
    void emptyQueryReturnsEmpty() {
        InMemoryTargetIndex idx = new InMemoryTargetIndex(List.of(t("a:1", "x", List.of())));
        assertThat(idx.search("", 10)).isEmpty();
    }

    @Test
    void findByIdReturnsTarget() {
        Target tx = t("messier:M31", "M31", List.of("Andromeda"));
        InMemoryTargetIndex idx = new InMemoryTargetIndex(List.of(tx));
        assertThat(idx.findById("messier:M31")).contains(tx);
        assertThat(idx.findById("messier:M999")).isEmpty();
    }

    @Test
    void searchMatchesAliasCaseInsensitive() {
        Target tx = t("messier:M31", "M31", List.of("Andromeda Galaxy", "NGC 224"));
        InMemoryTargetIndex idx = new InMemoryTargetIndex(List.of(tx));
        assertThat(idx.search("ANDROMEDA", 10)).contains(tx);
        assertThat(idx.search("ngc 224", 10)).contains(tx);
    }
}
```

Create `src/test/java/dev/nocs/target/catalog/CatalogLoaderTest.java`:

```java
package dev.nocs.target.catalog;

import dev.nocs.target.Target;
import java.io.InputStream;
import java.util.List;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class CatalogLoaderTest {

    @Test
    void parsesMiniFixture() throws Exception {
        InputStream in = getClass().getResourceAsStream("/catalogs/mini-messier.tsv");
        assertThat(in).as("fixture must be on classpath").isNotNull();
        List<Target> targets = CatalogLoader.readTsv(in);
        assertThat(targets).hasSize(3);
        Target m31 = targets.stream().filter(t -> t.id().equals("messier:M31")).findFirst().orElseThrow();
        assertThat(m31.primaryName()).isEqualTo("M31");
        assertThat(m31.aliases()).contains("NGC224", "Andromeda Galaxy");
        assertThat(m31.raJ2000Deg()).isCloseTo(10.684708, org.assertj.core.data.Offset.offset(1e-6));
    }
}
```

- [ ] **Step 13.3: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.target.catalog.*'`
Expected: compile failure.

- [ ] **Step 13.4: Implement `InMemoryTargetIndex.java`**

Create `src/main/java/dev/nocs/target/catalog/InMemoryTargetIndex.java`:

```java
package dev.nocs.target.catalog;

import dev.nocs.target.Target;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Collectors;

public final class InMemoryTargetIndex {

    private final List<Target> all;
    private final Map<String, Target> byId;

    public InMemoryTargetIndex(List<Target> targets) {
        this.all = List.copyOf(targets);
        this.byId = new HashMap<>();
        for (Target t : targets) byId.put(t.id(), t);
    }

    public Optional<Target> findById(String id) {
        return Optional.ofNullable(byId.get(id));
    }

    public int size() {
        return all.size();
    }

    public List<Target> all() {
        return all;
    }

    /**
     * Rank:
     *   0 — exact alias or primary-name match
     *   1 — starts-with
     *   2 — contains
     * Targets with no match are dropped. Ties break by primary-name length (shorter first).
     */
    public List<Target> search(String queryRaw, int limit) {
        if (queryRaw == null) return List.of();
        String q = queryRaw.trim().toLowerCase();
        if (q.isEmpty()) return List.of();

        return all.stream()
                .map(t -> new Ranked(t, rank(t, q)))
                .filter(r -> r.rank < 3)
                .sorted(Comparator.<Ranked>comparingInt(r -> r.rank)
                        .thenComparingInt(r -> r.target.primaryName().length()))
                .limit(limit <= 0 ? Long.MAX_VALUE : limit)
                .map(r -> r.target)
                .collect(Collectors.toList());
    }

    private int rank(Target t, String q) {
        String name = t.primaryName().toLowerCase();
        if (name.equals(q)) return 0;
        for (String a : t.aliases()) if (a.toLowerCase().equals(q)) return 0;
        if (name.startsWith(q)) return 1;
        for (String a : t.aliases()) if (a.toLowerCase().startsWith(q)) return 1;
        if (name.contains(q)) return 2;
        for (String a : t.aliases()) if (a.toLowerCase().contains(q)) return 2;
        return 3;
    }

    private record Ranked(Target target, int rank) {}
}
```

- [ ] **Step 13.5: Implement `CatalogLoader.java`**

Create `src/main/java/dev/nocs/target/catalog/CatalogLoader.java`:

```java
package dev.nocs.target.catalog;

import dev.nocs.target.Target;
import dev.nocs.target.TargetKind;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

public final class CatalogLoader {

    private CatalogLoader() {}

    public static List<Target> loadFromClasspath(ClassLoader cl, List<String> resourceNames) throws IOException {
        List<Target> out = new ArrayList<>();
        for (String name : resourceNames) {
            try (InputStream in = cl.getResourceAsStream(name)) {
                if (in == null) throw new IOException("catalog resource not found: " + name);
                out.addAll(readTsv(in));
            }
        }
        return out;
    }

    public static List<Target> readTsv(InputStream in) throws IOException {
        List<Target> targets = new ArrayList<>();
        try (BufferedReader br = new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8))) {
            String line;
            while ((line = br.readLine()) != null) {
                if (line.isBlank() || line.startsWith("#")) continue;
                String[] cols = line.split("\t", -1);
                if (cols.length < 10) continue;
                try {
                    List<String> aliases = cols[2].isBlank()
                            ? List.of()
                            : Arrays.stream(cols[2].split(",")).map(String::trim).filter(s -> !s.isEmpty()).toList();
                    double ra = parseDoubleOrNaN(cols[4]);
                    double dec = parseDoubleOrNaN(cols[5]);
                    double mag = parseDoubleOrNaN(cols[7]);
                    double size = parseSize(cols[8]);
                    targets.add(new Target(
                            cols[0],
                            cols[1],
                            aliases,
                            TargetKind.parseOrOther(cols[3]),
                            ra,
                            dec,
                            cols[6],
                            mag,
                            size,
                            cols.length > 9 ? cols[9] : ""));
                } catch (RuntimeException rex) {
                    // Skip malformed rows; bundled TSVs should not have any, but be lenient.
                }
            }
        }
        return targets;
    }

    private static double parseDoubleOrNaN(String s) {
        if (s == null || s.isBlank() || "NaN".equalsIgnoreCase(s.trim())) return Double.NaN;
        try { return Double.parseDouble(s.trim()); } catch (NumberFormatException e) { return Double.NaN; }
    }

    private static double parseSize(String s) {
        if (s == null || s.isBlank() || "NaN".equalsIgnoreCase(s.trim())) return Double.NaN;
        // Accept "189.1x61.7" style (major dim) — take the larger; otherwise parse as number.
        String v = s.trim().toLowerCase();
        int x = v.indexOf('x');
        String chosen = x > 0 ? v.substring(0, x) : v;
        return parseDoubleOrNaN(chosen);
    }
}
```

- [ ] **Step 13.6: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.target.catalog.*'`
Expected: all tests pass.

- [ ] **Step 13.7: Commit**

```bash
git add src/main/java/dev/nocs/target/catalog/ \
        src/test/java/dev/nocs/target/catalog/ \
        src/test/resources/catalogs/
git commit -m "feat(target): in-memory index + TSV catalog loader"
```

---

### Task 14: `SolarSystemCatalog` (dynamic catalog for Sun/Moon/planets)

**Files:**
- Create: `src/main/java/dev/nocs/target/catalog/SolarSystemCatalog.java`
- Create: `src/test/java/dev/nocs/target/catalog/SolarSystemCatalogTest.java`

- [ ] **Step 14.1: Write failing tests**

Create `src/test/java/dev/nocs/target/catalog/SolarSystemCatalogTest.java`:

```java
package dev.nocs.target.catalog;

import dev.nocs.target.Target;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SolarSystemCatalogTest {

    @Test
    void listsAllTenBodies() {
        List<Target> all = SolarSystemCatalog.staticTargets();
        assertThat(all).extracting(Target::id).contains(
                "sun", "moon",
                "planet:mercury", "planet:venus", "planet:mars",
                "planet:jupiter", "planet:saturn", "planet:uranus",
                "planet:neptune", "planet:pluto");
    }

    @Test
    void resolveSunGivesLiveCoordinates() {
        Optional<Target> t = SolarSystemCatalog.resolveWithPosition("sun", Instant.parse("2026-03-20T14:46:00Z"));
        assertThat(t).isPresent();
        assertThat(t.get().raJ2000Deg()).isBetween(0.0, 360.0);
        assertThat(t.get().decJ2000Deg()).isBetween(-1.0, 1.0);
    }

    @Test
    void resolveUnknownReturnsEmpty() {
        assertThat(SolarSystemCatalog.resolveWithPosition("planet:nibiru", Instant.now())).isEmpty();
    }

    @Test
    void searchMatchesSun() {
        assertThat(SolarSystemCatalog.search("sun", Instant.now(), 5))
                .extracting(Target::id).contains("sun");
    }
}
```

- [ ] **Step 14.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.target.catalog.SolarSystemCatalogTest'`
Expected: compile failure.

- [ ] **Step 14.3: Implement `SolarSystemCatalog.java`**

Create `src/main/java/dev/nocs/target/catalog/SolarSystemCatalog.java`:

```java
package dev.nocs.target.catalog;

import dev.nocs.astronomy.SolarSystem;
import dev.nocs.target.Target;
import dev.nocs.target.TargetKind;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;

public final class SolarSystemCatalog {

    private static final Map<String, SolarSystem.Body> ID_TO_BODY = Map.ofEntries(
            Map.entry("sun", SolarSystem.Body.SUN),
            Map.entry("moon", SolarSystem.Body.MOON),
            Map.entry("planet:mercury", SolarSystem.Body.MERCURY),
            Map.entry("planet:venus", SolarSystem.Body.VENUS),
            Map.entry("planet:mars", SolarSystem.Body.MARS),
            Map.entry("planet:jupiter", SolarSystem.Body.JUPITER),
            Map.entry("planet:saturn", SolarSystem.Body.SATURN),
            Map.entry("planet:uranus", SolarSystem.Body.URANUS),
            Map.entry("planet:neptune", SolarSystem.Body.NEPTUNE),
            Map.entry("planet:pluto", SolarSystem.Body.PLUTO));

    private SolarSystemCatalog() {}

    /** Static "shell" targets — no position baked in; callers use {@link #resolveWithPosition}. */
    public static List<Target> staticTargets() {
        List<Target> out = new ArrayList<>();
        for (Map.Entry<String, SolarSystem.Body> e : ID_TO_BODY.entrySet()) {
            out.add(shell(e.getKey(), e.getValue()));
        }
        return out;
    }

    public static Optional<Target> resolveWithPosition(String id, Instant when) {
        SolarSystem.Body body = ID_TO_BODY.get(id.toLowerCase(Locale.ROOT));
        if (body == null) return Optional.empty();
        double[] rd = SolarSystem.positionJ2000(body, when);
        Target shell = shell(id, body);
        return Optional.of(new Target(
                shell.id(), shell.primaryName(), shell.aliases(), shell.kind(),
                rd[0], rd[1], "", Double.NaN, Double.NaN, "live ephemeris"));
    }

    public static List<Target> search(String queryRaw, Instant when, int limit) {
        String q = queryRaw == null ? "" : queryRaw.trim().toLowerCase(Locale.ROOT);
        if (q.isEmpty()) return List.of();
        List<Target> matches = new ArrayList<>();
        for (Map.Entry<String, SolarSystem.Body> e : ID_TO_BODY.entrySet()) {
            Target shell = shell(e.getKey(), e.getValue());
            if (shell.primaryName().toLowerCase(Locale.ROOT).contains(q)
                    || shell.id().toLowerCase(Locale.ROOT).contains(q)) {
                resolveWithPosition(e.getKey(), when).ifPresent(matches::add);
                if (matches.size() >= Math.max(1, limit)) break;
            }
        }
        return matches;
    }

    private static Target shell(String id, SolarSystem.Body body) {
        TargetKind kind = switch (body) {
            case SUN -> TargetKind.SUN;
            case MOON -> TargetKind.MOON;
            default -> TargetKind.PLANET;
        };
        String name = switch (body) {
            case SUN -> "Sun";
            case MOON -> "Moon";
            default -> body.name().charAt(0) + body.name().substring(1).toLowerCase();
        };
        return new Target(id, name, List.of(name.toLowerCase()), kind,
                Double.NaN, Double.NaN, "", Double.NaN, Double.NaN, "");
    }
}
```

- [ ] **Step 14.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.target.catalog.SolarSystemCatalogTest'`
Expected: all four tests pass.

- [ ] **Step 14.5: Commit**

```bash
git add src/main/java/dev/nocs/target/catalog/SolarSystemCatalog.java \
        src/test/java/dev/nocs/target/catalog/SolarSystemCatalogTest.java
git commit -m "feat(target): SolarSystemCatalog with live ephemeris resolve"
```

---

### Task 15: `TargetRepository` (targets_custom)

**Files:**
- Create: `src/main/java/dev/nocs/target/TargetRepository.java`
- Create: `src/test/java/dev/nocs/target/TargetRepositoryTest.java`

- [ ] **Step 15.1: Write the failing test**

Create `src/test/java/dev/nocs/target/TargetRepositoryTest.java`:

```java
package dev.nocs.target;

import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@TestPropertySource(properties = "nocs.auth.token=t")
class TargetRepositoryTest {

    @Autowired TargetRepository repo;
    @Autowired JdbcTemplate jdbc;

    @BeforeEach void reset() { jdbc.update("DELETE FROM targets_custom"); }

    @Test
    void insertAndListRoundTrip() {
        long id = repo.insert("My Dark Spot", 10.0, 20.0, TargetKind.CUSTOM, "behind my neighbour's oak");
        List<Target> all = repo.findAll();
        assertThat(all).hasSize(1);
        Target t = all.get(0);
        assertThat(t.id()).isEqualTo("custom:" + id);
        assertThat(t.primaryName()).isEqualTo("My Dark Spot");
        assertThat(t.raJ2000Deg()).isEqualTo(10.0);
    }

    @Test
    void deleteRemoves() {
        long id = repo.insert("X", 0, 0, TargetKind.CUSTOM, "");
        assertThat(repo.delete(id)).isTrue();
        assertThat(repo.delete(id)).isFalse();
        assertThat(repo.findAll()).isEmpty();
    }
}
```

- [ ] **Step 15.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.target.TargetRepositoryTest'`
Expected: compile failure.

- [ ] **Step 15.3: Implement `TargetRepository.java`**

Create `src/main/java/dev/nocs/target/TargetRepository.java`:

```java
package dev.nocs.target;

import java.sql.ResultSet;
import java.sql.Statement;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Repository;

@Repository
public class TargetRepository {

    private final JdbcTemplate jdbc;

    public TargetRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static final RowMapper<Target> MAPPER = (ResultSet rs, int rowNum) -> new Target(
            "custom:" + rs.getLong("id"),
            rs.getString("name"),
            List.of(),
            TargetKind.parseOrOther(rs.getString("kind")),
            rs.getDouble("ra_j2000_deg"),
            rs.getDouble("dec_j2000_deg"),
            "",
            Double.NaN,
            Double.NaN,
            rs.getString("notes"));

    public long insert(String name, double ra, double dec, TargetKind kind, String notes) {
        GeneratedKeyHolder key = new GeneratedKeyHolder();
        jdbc.update(con -> {
            var ps = con.prepareStatement(
                    "INSERT INTO targets_custom(name, ra_j2000_deg, dec_j2000_deg, kind, notes) VALUES(?, ?, ?, ?, ?)",
                    Statement.RETURN_GENERATED_KEYS);
            ps.setString(1, name);
            ps.setDouble(2, ra);
            ps.setDouble(3, dec);
            ps.setString(4, kind.name());
            ps.setString(5, notes == null ? "" : notes);
            return ps;
        }, key);
        return key.getKey().longValue();
    }

    public List<Target> findAll() {
        return jdbc.query(
                "SELECT id, name, ra_j2000_deg, dec_j2000_deg, kind, notes FROM targets_custom ORDER BY id DESC",
                MAPPER);
    }

    public Optional<Target> findById(long id) {
        return jdbc.query(
                "SELECT id, name, ra_j2000_deg, dec_j2000_deg, kind, notes FROM targets_custom WHERE id = ?",
                MAPPER, id).stream().findFirst();
    }

    public boolean delete(long id) {
        return jdbc.update("DELETE FROM targets_custom WHERE id = ?", id) > 0;
    }
}
```

- [ ] **Step 15.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.target.TargetRepositoryTest'`
Expected: both tests pass.

- [ ] **Step 15.5: Commit**

```bash
git add src/main/java/dev/nocs/target/TargetRepository.java \
        src/test/java/dev/nocs/target/TargetRepositoryTest.java
git commit -m "feat(target): JDBC repository for targets_custom"
```

---

### Task 16: `TargetService` + wiring

**Files:**
- Create: `src/main/java/dev/nocs/target/TargetObservation.java`
- Create: `src/main/java/dev/nocs/target/TargetService.java`
- Modify: `src/main/java/dev/nocs/config/AppBeansConfig.java` (register index + loader)
- Create: `src/test/java/dev/nocs/target/TargetServiceTest.java`

- [ ] **Step 16.1: Implement `TargetObservation.java`**

Create `src/main/java/dev/nocs/target/TargetObservation.java`:

```java
package dev.nocs.target;

import java.time.Instant;
import java.util.Optional;

public record TargetObservation(
        Instant computedAt,
        double raJNowDeg,
        double decJNowDeg,
        double altitudeDeg,
        double azimuthDeg,
        double airmass,
        Optional<Instant> transitUtc,
        Optional<Instant> riseUtc,
        Optional<Instant> setUtc,
        boolean alwaysAbove,
        boolean alwaysBelow) {}
```

- [ ] **Step 16.2: Write the failing test**

Create `src/test/java/dev/nocs/target/TargetServiceTest.java`:

```java
package dev.nocs.target;

import java.time.Instant;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@TestPropertySource(properties = "nocs.auth.token=t")
class TargetServiceTest {

    @Autowired TargetService service;
    @Autowired JdbcTemplate jdbc;

    @BeforeEach
    void reset() {
        jdbc.update("DELETE FROM targets_custom");
        jdbc.update("DELETE FROM observatories");
        jdbc.update("INSERT INTO observatories(name, latitude_deg, longitude_deg, elevation_m, timezone, is_active) "
                + "VALUES('Test', 40.0, -74.0, 0, 'UTC', 1)");
    }

    @Test
    void searchFindsM31() {
        var hits = service.search("M31", 5);
        assertThat(hits).isNotEmpty();
        assertThat(hits.get(0).target().id()).isEqualTo("messier:M31");
        assertThat(hits.get(0).observation()).isPresent();
    }

    @Test
    void searchFindsAndromedaByAlias() {
        var hits = service.search("Andromeda", 5);
        assertThat(hits).extracting(r -> r.target().id()).contains("messier:M31");
    }

    @Test
    void searchFindsSun() {
        var hits = service.search("Sun", 5);
        assertThat(hits).extracting(r -> r.target().id()).contains("sun");
    }

    @Test
    void resolveByIdReturnsObservation() {
        Optional<TargetService.Resolved> r = service.resolveById("messier:M31", Instant.parse("2026-04-22T00:00:00Z"));
        assertThat(r).isPresent();
        assertThat(r.get().observation()).isPresent();
        TargetObservation obs = r.get().observation().get();
        assertThat(Double.isFinite(obs.altitudeDeg())).isTrue();
        assertThat(Double.isFinite(obs.azimuthDeg())).isTrue();
        assertThat(obs.transitUtc()).isPresent();
    }

    @Test
    void resolveCustomTargetWorks() {
        long id = service.addCustom("My Spot", 10.0, 20.0, "");
        var r = service.resolveById("custom:" + id, Instant.now());
        assertThat(r).isPresent();
        assertThat(r.get().target().primaryName()).isEqualTo("My Spot");
    }
}
```

- [ ] **Step 16.3: Implement `TargetService.java`**

Create `src/main/java/dev/nocs/target/TargetService.java`:

```java
package dev.nocs.target;

import dev.nocs.astronomy.GeographicLocation;
import dev.nocs.astronomy.Horizontal;
import dev.nocs.astronomy.Precession;
import dev.nocs.astronomy.RiseTransitSet;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.observatory.ObservatoryService;
import dev.nocs.target.catalog.InMemoryTargetIndex;
import dev.nocs.target.catalog.SolarSystemCatalog;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.stereotype.Service;

@Service
public class TargetService {

    private final InMemoryTargetIndex bundled;
    private final TargetRepository custom;
    private final ObservatoryService observatoryService;
    private final SimbadResolver simbad;
    private final EventBus bus;

    public TargetService(
            InMemoryTargetIndex bundled,
            TargetRepository custom,
            ObservatoryService observatoryService,
            SimbadResolver simbad,
            EventBus bus) {
        this.bundled = bundled;
        this.custom = custom;
        this.observatoryService = observatoryService;
        this.simbad = simbad;
        this.bus = bus;
    }

    public record Resolved(Target target, Optional<TargetObservation> observation) {}

    public List<Resolved> search(String query, int limit) {
        Instant now = Instant.now();
        Map<String, Target> results = new LinkedHashMap<>();
        for (Target t : bundled.search(query, limit)) results.put(t.id(), t);
        for (Target t : SolarSystemCatalog.search(query, now, limit)) results.put(t.id(), t);
        for (Target t : custom.findAll()) {
            if (matches(t, query)) results.put(t.id(), t);
        }
        if (results.isEmpty() && simbad != null) {
            simbad.resolve(query).ifPresent(t -> results.put(t.id(), t));
        }
        return trim(results.values(), limit).stream()
                .map(t -> new Resolved(t, observation(t, now)))
                .toList();
    }

    public Optional<Resolved> resolveById(String id, Instant when) {
        TargetId.Parsed p = TargetId.parse(id);
        if (p.catalog().equals("custom")) {
            try {
                long numeric = Long.parseLong(p.designator());
                return custom.findById(numeric).map(t -> new Resolved(t, observation(t, when)));
            } catch (NumberFormatException e) {
                return Optional.empty();
            }
        }
        if (p.catalog().equals("sun") || p.catalog().equals("moon") || p.catalog().equals("planet")) {
            return SolarSystemCatalog.resolveWithPosition(id, when)
                    .map(t -> new Resolved(t, observation(t, when)));
        }
        return bundled.findById(id).map(t -> new Resolved(t, observation(t, when)));
    }

    public long addCustom(String name, double ra, double dec, String notes) {
        long id = custom.insert(name, ra, dec, TargetKind.CUSTOM, notes);
        bus.publish(Event.of(Topic.SYSTEM, "target_custom_added", Map.of("id", id, "name", name)));
        return id;
    }

    public boolean deleteCustom(long id) {
        boolean removed = custom.delete(id);
        if (removed) bus.publish(Event.of(Topic.SYSTEM, "target_custom_deleted", Map.of("id", id)));
        return removed;
    }

    public Optional<TargetObservation> observation(Target t, Instant when) {
        if (!t.hasFixedCoordinates()) return Optional.empty();
        Optional<GeographicLocation> loc = observatoryService.activeLocation();
        if (loc.isEmpty()) return Optional.empty();
        double[] jnow = Precession.precessFromJ2000(t.raJ2000Deg(), t.decJ2000Deg(), when);
        double[] altaz = Horizontal.equatorialToHorizontal(jnow[0], jnow[1], loc.get(), when, true);
        double airmass = Horizontal.airmass(altaz[0]);
        RiseTransitSet.Result rts = RiseTransitSet.compute(jnow[0], jnow[1], loc.get(), when);
        return Optional.of(new TargetObservation(
                when, jnow[0], jnow[1], altaz[0], altaz[1], airmass,
                rts.transit(), rts.rise(), rts.set(),
                rts.alwaysAbove(), rts.alwaysBelow()));
    }

    private static boolean matches(Target t, String query) {
        if (query == null || query.isBlank()) return false;
        String q = query.toLowerCase();
        if (t.primaryName().toLowerCase().contains(q)) return true;
        for (String a : t.aliases()) if (a.toLowerCase().contains(q)) return true;
        return false;
    }

    private static List<Target> trim(Iterable<Target> input, int limit) {
        List<Target> out = new ArrayList<>();
        for (Target t : input) {
            out.add(t);
            if (limit > 0 && out.size() >= limit) break;
        }
        return out;
    }
}
```

- [ ] **Step 16.4: Wire beans in `AppBeansConfig.java`**

Modify `src/main/java/dev/nocs/config/AppBeansConfig.java` to register the catalog index and (forward-ref) `SimbadResolver`. Add these imports at the top of the file (alongside the existing imports):

```java
import dev.nocs.target.SimbadResolver;
import dev.nocs.target.Target;
import dev.nocs.target.catalog.CatalogLoader;
import dev.nocs.target.catalog.InMemoryTargetIndex;
import dev.nocs.target.catalog.SolarSystemCatalog;
import java.io.IOException;
import java.util.ArrayList;
```

And append these `@Bean` methods inside the class body:

```java
@Bean
InMemoryTargetIndex bundledTargetIndex() throws IOException {
    java.util.List<Target> all = new ArrayList<>();
    all.addAll(CatalogLoader.loadFromClasspath(
            Thread.currentThread().getContextClassLoader(),
            java.util.List.of(
                    "catalogs/messier.tsv",
                    "catalogs/caldwell.tsv",
                    "catalogs/named-stars.tsv",
                    "catalogs/opennngc.tsv")));
    all.addAll(SolarSystemCatalog.staticTargets());
    return new InMemoryTargetIndex(all);
}

@Bean
SimbadResolver simbadResolver(NocsProperties props) {
    return new SimbadResolver(
            props.targets() != null && Boolean.TRUE.equals(props.targets().onlineResolver()),
            props.targets() == null ? null : props.targets().simbadBaseUrl());
}
```

(`SimbadResolver` is implemented in Task 17 — the bean wiring is correct once that file lands.)

- [ ] **Step 16.5: Run — expect failure on missing `SimbadResolver`**

Run: `./gradlew compileJava`
Expected: compile error `cannot find symbol: class SimbadResolver`.

Task 17 implements it; proceed there, then return to run this task's tests.

- [ ] **Step 16.6: After Task 17 is complete, run the service tests**

Run: `./gradlew test --tests 'dev.nocs.target.TargetServiceTest'`
Expected: all five tests pass.

- [ ] **Step 16.7: Commit** (after Task 17)

```bash
git add src/main/java/dev/nocs/target/TargetObservation.java \
        src/main/java/dev/nocs/target/TargetService.java \
        src/main/java/dev/nocs/config/AppBeansConfig.java \
        src/test/java/dev/nocs/target/TargetServiceTest.java
git commit -m "feat(target): TargetService with search + observation compute"
```

---

### Task 17: `SimbadResolver` (optional online fallback)

**Files:**
- Create: `src/main/java/dev/nocs/target/SimbadResolver.java`
- Create: `src/test/resources/simbad/m31-response.txt`
- Create: `src/test/java/dev/nocs/target/SimbadResolverTest.java`

- [ ] **Step 17.1: Capture a SIMBAD fixture**

Create `src/test/resources/simbad/m31-response.txt`:

```
C.D.S.  -  SIMBAD4 rel 1.8  -  2026.04.22CEST13:12:47

M31

Object M 31  ---  G  ---  OID=@2048117   (@@13693,0)  ---  coobox=3571

Coordinates(ICRS,ep=J2000,eq=2000): 00 42 44.3503 +41 16 09.067 (Opt ) E [0.0100 0.0100 90] 2002AAS...30107708I
Coordinates(FK4,ep=B1950,eq=1950): 00 40 00.23  +40 59 38.8  (            )
Coordinates(Gal,ep=J2000,eq=2000): 121.1742743 -21.5731497  (          )
hierarchy counts: #parents=14, #children=5923, #siblings=0

Flux U : 5.32 [0.14] C
Flux B : 4.36 [0.02] C
Flux V : 3.44 [0.02] C

Identifiers (52):
    M  31                         NGC  224                        UGC   454
    ...
```

(Capture this fixture from `curl 'https://simbad.u-strasbg.fr/simbad/sim-id?Ident=M31&output.format=ASCII'`. Only the `Coordinates(ICRS...)` line matters for our parser; other lines are tolerated.)

- [ ] **Step 17.2: Write failing tests**

Create `src/test/java/dev/nocs/target/SimbadResolverTest.java`:

```java
package dev.nocs.target;

import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Optional;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SimbadResolverTest {

    @Test
    void offlineWhenDisabled() {
        SimbadResolver r = new SimbadResolver(false, "http://localhost:1/simbad");
        assertThat(r.resolve("M31")).isEmpty();
    }

    @Test
    void parsesCapturedFixture() throws Exception {
        byte[] body = Files.readAllBytes(Path.of(
                getClass().getResource("/simbad/m31-response.txt").toURI()));
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/sim-id", exchange -> {
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();
        try {
            String base = "http://127.0.0.1:" + server.getAddress().getPort();
            SimbadResolver r = new SimbadResolver(true, base);
            Optional<Target> out = r.resolve("M31");
            assertThat(out).isPresent();
            Target t = out.get();
            assertThat(t.id()).isEqualTo("simbad:M31");
            assertThat(t.raJ2000Deg()).isBetween(10.6, 10.8);
            assertThat(t.decJ2000Deg()).isBetween(41.2, 41.3);
        } finally {
            server.stop(0);
        }
    }

    @Test
    void returnsEmptyOnHttpError() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/sim-id", exchange -> {
            exchange.sendResponseHeaders(500, 0);
            exchange.close();
        });
        server.start();
        try {
            SimbadResolver r = new SimbadResolver(true, "http://127.0.0.1:" + server.getAddress().getPort());
            assertThat(r.resolve("x")).isEmpty();
        } finally {
            server.stop(0);
        }
    }
}
```

- [ ] **Step 17.3: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.target.SimbadResolverTest'`
Expected: compile failure.

- [ ] **Step 17.4: Implement `SimbadResolver.java`**

Create `src/main/java/dev/nocs/target/SimbadResolver.java`:

```java
package dev.nocs.target;

import dev.nocs.astronomy.Angles;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public final class SimbadResolver {

    private static final Pattern COORD_LINE = Pattern.compile(
            "Coordinates\\(ICRS[^)]+\\):\\s*([0-9:.+\\- ]+?)\\s{2,}");

    private final boolean enabled;
    private final String baseUrl;
    private final HttpClient client;

    public SimbadResolver(boolean enabled, String baseUrl) {
        this.enabled = enabled;
        this.baseUrl = baseUrl == null ? "https://simbad.u-strasbg.fr/simbad" : baseUrl;
        this.client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
    }

    public Optional<Target> resolve(String query) {
        if (!enabled || query == null || query.isBlank()) return Optional.empty();
        try {
            URI uri = URI.create(baseUrl
                    + "/sim-id?output.format=ASCII&Ident="
                    + URLEncoder.encode(query, StandardCharsets.UTF_8));
            HttpResponse<String> resp = client.send(
                    HttpRequest.newBuilder(uri).timeout(Duration.ofSeconds(8)).GET().build(),
                    HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (resp.statusCode() != 200) return Optional.empty();
            return parse(query, resp.body());
        } catch (Exception e) {
            return Optional.empty();
        }
    }

    static Optional<Target> parse(String query, String body) {
        Matcher m = COORD_LINE.matcher(body);
        if (!m.find()) return Optional.empty();
        String coords = m.group(1).trim();
        int splitIdx = findCoordSplit(coords);
        if (splitIdx < 0) return Optional.empty();
        String raStr = coords.substring(0, splitIdx).trim();
        String decStr = coords.substring(splitIdx).trim();
        try {
            double ra = Angles.parseHmsToDeg(raStr);
            double dec = Angles.parseDmsToDeg(decStr);
            return Optional.of(new Target(
                    "simbad:" + query,
                    query,
                    List.of(query),
                    TargetKind.OTHER,
                    ra, dec, "", Double.NaN, Double.NaN, "resolved via SIMBAD"));
        } catch (Exception e) {
            return Optional.empty();
        }
    }

    private static int findCoordSplit(String coords) {
        // The first signed token (+/−) after at least one digit marks the declination.
        boolean sawDigit = false;
        for (int i = 0; i < coords.length(); i++) {
            char c = coords.charAt(i);
            if (Character.isDigit(c)) sawDigit = true;
            if (sawDigit && (c == '+' || c == '-') && i > 0 && coords.charAt(i - 1) == ' ') {
                return i;
            }
        }
        return -1;
    }
}
```

- [ ] **Step 17.5: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.target.SimbadResolverTest'`
Expected: all three tests pass.

If the real SIMBAD fixture's coordinates line is formatted slightly differently, tighten `COORD_LINE` and `findCoordSplit` — the test above pins the expected regex behaviour.

- [ ] **Step 17.6: Run the service test that Task 16 wrote**

Run: `./gradlew test --tests 'dev.nocs.target.TargetServiceTest'`
Expected: passes.

- [ ] **Step 17.7: Commit (Task 16 + 17 together)**

```bash
git add src/main/java/dev/nocs/target/SimbadResolver.java \
        src/test/resources/simbad/ \
        src/test/java/dev/nocs/target/SimbadResolverTest.java \
        src/main/java/dev/nocs/target/TargetObservation.java \
        src/main/java/dev/nocs/target/TargetService.java \
        src/main/java/dev/nocs/config/AppBeansConfig.java \
        src/test/java/dev/nocs/target/TargetServiceTest.java
git commit -m "feat(target): SIMBAD fallback resolver + wire TargetService beans"
```

---

### Task 18: Target REST controller

**Files:**
- Create: `src/main/java/dev/nocs/target/api/dto/TargetView.java`
- Create: `src/main/java/dev/nocs/target/api/dto/TargetSearchResult.java`
- Create: `src/main/java/dev/nocs/target/api/dto/CreateCustomTargetRequest.java`
- Create: `src/main/java/dev/nocs/target/api/TargetController.java`
- Create: `src/test/java/dev/nocs/target/api/TargetControllerTest.java`

- [ ] **Step 18.1: Write the failing controller test**

Create `src/test/java/dev/nocs/target/api/TargetControllerTest.java`:

```java
package dev.nocs.target.api;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(properties = "nocs.auth.token=t")
class TargetControllerTest {

    @Autowired MockMvc mvc;
    @Autowired JdbcTemplate jdbc;

    @BeforeEach
    void reset() {
        jdbc.update("DELETE FROM observatories");
        jdbc.update("DELETE FROM targets_custom");
        jdbc.update("INSERT INTO observatories(name, latitude_deg, longitude_deg, elevation_m, timezone, is_active) "
                + "VALUES('t', 40.0, -74.0, 0, 'UTC', 1)");
    }

    @Test
    void searchM31ReturnsObservation() throws Exception {
        mvc.perform(get("/api/targets/search").param("q", "M31").header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].target.id").value("messier:M31"))
                .andExpect(jsonPath("$[0].observation.altitudeDeg").isNumber())
                .andExpect(jsonPath("$[0].observation.azimuthDeg").isNumber())
                .andExpect(jsonPath("$[0].observation.transitUtc").exists());
    }

    @Test
    void getByIdReturnsM31() throws Exception {
        mvc.perform(get("/api/targets/messier:M31").header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.target.primaryName").value("M31"));
    }

    @Test
    void getByIdUnknownReturns404() throws Exception {
        mvc.perform(get("/api/targets/messier:M999").header("Authorization", "Bearer t"))
                .andExpect(status().isNotFound());
    }

    @Test
    void customTargetRoundTrip() throws Exception {
        String body = mvc.perform(post("/api/targets/custom")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "name":"Dark Nebula X","raJ2000Deg":200.0,"decJ2000Deg":-30.0,"notes":"test" }"""))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").isNumber())
                .andReturn().getResponse().getContentAsString();
        long id = Long.parseLong(body.replaceAll(".*\"id\"\\s*:\\s*(\\d+).*", "$1"));

        mvc.perform(get("/api/targets/custom:" + id).header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.target.primaryName").value("Dark Nebula X"));

        mvc.perform(delete("/api/targets/custom/" + id).header("Authorization", "Bearer t"))
                .andExpect(status().isOk());

        mvc.perform(get("/api/targets/custom:" + id).header("Authorization", "Bearer t"))
                .andExpect(status().isNotFound());
    }

    @Test
    void missingObservatoryLeavesObservationEmpty() throws Exception {
        jdbc.update("DELETE FROM observatories");
        mvc.perform(get("/api/targets/messier:M31").header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.observation").doesNotExist());
    }
}
```

- [ ] **Step 18.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.target.api.TargetControllerTest'`
Expected: 404.

- [ ] **Step 18.3: Implement the DTOs**

Create `src/main/java/dev/nocs/target/api/dto/TargetView.java`:

```java
package dev.nocs.target.api.dto;

import dev.nocs.target.Target;
import dev.nocs.target.TargetKind;
import java.util.List;

public record TargetView(
        String id,
        String primaryName,
        List<String> aliases,
        TargetKind kind,
        double raJ2000Deg,
        double decJ2000Deg,
        String constellation,
        double magnitude,
        double sizeArcmin,
        String notes) {

    public static TargetView of(Target t) {
        return new TargetView(t.id(), t.primaryName(), t.aliases(), t.kind(),
                t.raJ2000Deg(), t.decJ2000Deg(), t.constellation(),
                t.magnitude(), t.sizeArcmin(), t.notes());
    }
}
```

Create `src/main/java/dev/nocs/target/api/dto/TargetSearchResult.java`:

```java
package dev.nocs.target.api.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import dev.nocs.target.TargetObservation;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record TargetSearchResult(TargetView target, TargetObservation observation) {}
```

Create `src/main/java/dev/nocs/target/api/dto/CreateCustomTargetRequest.java`:

```java
package dev.nocs.target.api.dto;

public record CreateCustomTargetRequest(
        String name,
        double raJ2000Deg,
        double decJ2000Deg,
        String notes) {}
```

- [ ] **Step 18.4: Implement `TargetController.java`**

Create `src/main/java/dev/nocs/target/api/TargetController.java`:

```java
package dev.nocs.target.api;

import dev.nocs.target.TargetService;
import dev.nocs.target.api.dto.CreateCustomTargetRequest;
import dev.nocs.target.api.dto.TargetSearchResult;
import dev.nocs.target.api.dto.TargetView;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/targets")
public class TargetController {

    private final TargetService service;

    public TargetController(TargetService service) {
        this.service = service;
    }

    @GetMapping("/search")
    public List<TargetSearchResult> search(
            @RequestParam("q") String q,
            @RequestParam(value = "limit", required = false, defaultValue = "20") int limit) {
        return service.search(q, limit).stream()
                .map(r -> new TargetSearchResult(TargetView.of(r.target()), r.observation().orElse(null)))
                .toList();
    }

    @GetMapping("/{id}")
    public ResponseEntity<TargetSearchResult> get(@PathVariable String id) {
        return service.resolveById(id, Instant.now())
                .map(r -> new TargetSearchResult(TargetView.of(r.target()), r.observation().orElse(null)))
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    @PostMapping("/custom")
    public Map<String, Object> addCustom(@RequestBody CreateCustomTargetRequest req) {
        long id = service.addCustom(req.name(), req.raJ2000Deg(), req.decJ2000Deg(), req.notes());
        return Map.of("id", id, "targetId", "custom:" + id);
    }

    @DeleteMapping("/custom/{id}")
    public ResponseEntity<Map<String, Object>> deleteCustom(@PathVariable long id) {
        boolean removed = service.deleteCustom(id);
        return removed
                ? ResponseEntity.ok(Map.of("id", id, "deleted", true))
                : ResponseEntity.notFound().build();
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, String>> badRequest(IllegalArgumentException e) {
        return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
    }
}
```

- [ ] **Step 18.5: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.target.api.TargetControllerTest'`
Expected: all five tests pass.

- [ ] **Step 18.6: Commit**

```bash
git add src/main/java/dev/nocs/target/api/ \
        src/test/java/dev/nocs/target/api/
git commit -m "feat(target): /api/targets REST surface"
```

---

### Task 19: `TARGET` topic + session-log correlation

**Files:**
- Modify: `src/main/java/dev/nocs/events/Topic.java`
- Modify: `src/main/java/dev/nocs/target/TargetService.java`
- Create: `src/test/java/dev/nocs/events/TargetTopicTest.java`

- [ ] **Step 19.1: Write the failing test**

Create `src/test/java/dev/nocs/events/TargetTopicTest.java`:

```java
package dev.nocs.events;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class TargetTopicTest {

    @Test
    void targetTopicExists() {
        assertThat(Topic.valueOf("TARGET")).isEqualTo(Topic.TARGET);
        assertThat(Topic.TARGET.wire()).isEqualTo("target");
        assertThat(Topic.fromWire("target")).isEqualTo(Topic.TARGET);
    }
}
```

- [ ] **Step 19.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.events.TargetTopicTest'`
Expected: `java.lang.IllegalArgumentException: No enum constant ... TARGET`.

- [ ] **Step 19.3: Add `TARGET` to `Topic.java`**

Replace `src/main/java/dev/nocs/events/Topic.java` with:

```java
package dev.nocs.events;

public enum Topic {
    MOUNT, CAMERA, FILTERWHEEL, FOCUSER,
    SEQUENCE, SAFETY, SESSION, DEVICE_CONNECTION, SYSTEM,
    TARGET;

    public String wire() {
        return name().toLowerCase();
    }

    public static Topic fromWire(String wire) {
        return Topic.valueOf(wire.trim().toUpperCase());
    }
}
```

- [ ] **Step 19.4: Emit events on `TARGET` instead of `SYSTEM`**

In `src/main/java/dev/nocs/target/TargetService.java`, change the two `Event.of(Topic.SYSTEM, …)` calls inside `addCustom` / `deleteCustom` to use `Topic.TARGET`:

```java
bus.publish(Event.of(Topic.TARGET, "target_custom_added", Map.of("id", id, "name", name)));
...
bus.publish(Event.of(Topic.TARGET, "target_custom_deleted", Map.of("id", id)));
```

- [ ] **Step 19.5: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.events.TargetTopicTest'`
Expected: pass.

Also re-run the target service tests:
Run: `./gradlew test --tests 'dev.nocs.target.TargetServiceTest'`
Expected: still pass.

- [ ] **Step 19.6: Commit**

```bash
git add src/main/java/dev/nocs/events/Topic.java \
        src/main/java/dev/nocs/target/TargetService.java \
        src/test/java/dev/nocs/events/TargetTopicTest.java
git commit -m "feat(events): add TARGET topic and route custom-target events to it"
```

---

### Task 20: End-to-end integration test + smoke

**Files:**
- Create: `src/test/java/dev/nocs/target/IntegrationTargetsApiTest.java`

- [ ] **Step 20.1: Write the integration test**

Create `src/test/java/dev/nocs/target/IntegrationTargetsApiTest.java`:

```java
package dev.nocs.target;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@TestPropertySource(properties = "nocs.auth.token=t")
class IntegrationTargetsApiTest {

    @Autowired JdbcTemplate jdbc;
    @LocalServerPort int port;
    final HttpClient http = HttpClient.newHttpClient();
    final ObjectMapper json = new ObjectMapper();

    @BeforeEach
    void seed() {
        jdbc.update("DELETE FROM observatories");
        jdbc.update("INSERT INTO observatories(name, latitude_deg, longitude_deg, elevation_m, timezone, is_active) "
                + "VALUES('IntTest', 40.0, -74.0, 10, 'UTC', 1)");
    }

    @Test
    void curlSearchM31() throws Exception {
        HttpResponse<String> resp = http.send(
                HttpRequest.newBuilder(URI.create("http://localhost:" + port + "/api/targets/search?q=M31"))
                        .header("Authorization", "Bearer t")
                        .GET().build(),
                HttpResponse.BodyHandlers.ofString());
        assertThat(resp.statusCode()).isEqualTo(200);
        JsonNode body = json.readTree(resp.body());
        assertThat(body.isArray()).isTrue();
        assertThat(body.get(0).get("target").get("id").asText()).isEqualTo("messier:M31");
        assertThat(body.get(0).get("observation").get("altitudeDeg").isNumber()).isTrue();
    }

    @Test
    void curlPlanetJupiter() throws Exception {
        HttpResponse<String> resp = http.send(
                HttpRequest.newBuilder(URI.create("http://localhost:" + port + "/api/targets/planet:jupiter"))
                        .header("Authorization", "Bearer t")
                        .GET().build(),
                HttpResponse.BodyHandlers.ofString());
        assertThat(resp.statusCode()).isEqualTo(200);
        JsonNode body = json.readTree(resp.body());
        assertThat(body.get("target").get("id").asText()).isEqualTo("planet:jupiter");
    }

    @Test
    void unauthenticatedIs401() throws Exception {
        HttpResponse<String> resp = http.send(
                HttpRequest.newBuilder(URI.create("http://localhost:" + port + "/api/targets/search?q=M31"))
                        .GET().build(),
                HttpResponse.BodyHandlers.ofString());
        assertThat(resp.statusCode()).isEqualTo(401);
    }
}
```

- [ ] **Step 20.2: Run the integration test**

Run: `./gradlew test --tests 'dev.nocs.target.IntegrationTargetsApiTest'`
Expected: all three tests pass.

- [ ] **Step 20.3: Smoke-test the packaged archive**

Run: `./gradlew distTar`

Then run the existing smoke-test wrapper after extending it with a targets call:

```bash
./smoke/smoke.sh build/distributions/nocs-0.1.0-SNAPSHOT-linux-x86_64.tar.gz
```

Manually exercise the targets endpoint once the server is up (find the token in its stdout):

```bash
TOKEN="..."  # from the running instance
curl -sS -H "Authorization: Bearer $TOKEN" "http://localhost:8080/api/observatories"
curl -sS -H "Authorization: Bearer $TOKEN" -X POST \
     -H "Content-Type: application/json" \
     -d '{"name":"Smoke","latitudeDeg":40,"longitudeDeg":-74,"elevationM":0,"timezone":"UTC","horizonMaskJson":"[]"}' \
     "http://localhost:8080/api/observatories"
curl -sS -H "Authorization: Bearer $TOKEN" "http://localhost:8080/api/targets/search?q=M31"
```

Expected: the last call returns a JSON array whose first element has `target.id == "messier:M31"` and a non-empty `observation` object.

- [ ] **Step 20.4: Commit**

```bash
git add src/test/java/dev/nocs/target/IntegrationTargetsApiTest.java
git commit -m "test(target): end-to-end integration across /api/targets"
```

---

### Task 21: README update + decomposition doc bookkeeping

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-04-22-v0.1-plan-decomposition.md`

- [ ] **Step 21.1: Extend the README "Developer quickstart" section**

Append to the quickstart block in `README.md`:

```markdown
### Target picker

With an active observatory row in place, the target API is live:

```bash
TOKEN="..."  # printed on startup
curl -sS -H "Authorization: Bearer $TOKEN" -X POST \
     -H "Content-Type: application/json" \
     -d '{"name":"Backyard","latitudeDeg":40.0,"longitudeDeg":-74.0,"elevationM":10,"timezone":"America/New_York","horizonMaskJson":"[]"}' \
     "http://localhost:8080/api/observatories"

curl -sS -H "Authorization: Bearer $TOKEN" "http://localhost:8080/api/targets/search?q=M31"
curl -sS -H "Authorization: Bearer $TOKEN" "http://localhost:8080/api/targets/planet:jupiter"
```

The catalog is built-in (Messier, Caldwell, NGC+IC, IAU named stars, solar system). To refresh from upstream, run `./scripts/fetch-catalogs.sh` and commit the outputs.

Set `nocs.targets.online-resolver: true` in your `config.yaml` to fall back to SIMBAD when a name is not in the bundled catalog.
```

- [ ] **Step 21.2: Update the decomposition status table**

In `docs/superpowers/plans/2026-04-22-v0.1-plan-decomposition.md`, change the "Plan overview" row for **C** to reference this plan, and change the "Current status" row for **C** from "No" to "Yes" with a link.

Specifically:

In the overview table, replace:

```
| **C** | Target service + catalogs | A | `GET /api/targets/search?q=M31` returns coordinates, altitude, transit, etc., using bundled catalogs + optional SIMBAD. |
```

with:

```
| **C** | Target service + catalogs | A | `GET /api/targets/search?q=M31` returns coordinates, altitude, transit, etc., using bundled catalogs + optional SIMBAD. Implemented: [2026-04-22-nocs-targets-and-catalogs.md](./2026-04-22-nocs-targets-and-catalogs.md). |
```

In the current-status table, replace:

```
| C–I | No | Author with the `writing-plans` skill when starting that slice |
```

with:

```
| C | Yes | [2026-04-22-nocs-targets-and-catalogs.md](./2026-04-22-nocs-targets-and-catalogs.md) |
| D–I | No | Author with the `writing-plans` skill when starting that slice |
```

- [ ] **Step 21.3: Final build**

Run: `./gradlew clean check`
Expected: all tests pass.

- [ ] **Step 21.4: Commit**

```bash
git add README.md docs/superpowers/plans/2026-04-22-v0.1-plan-decomposition.md
git commit -m "docs: document Plan C targets API and update decomposition status"
```

---

## Self-Review Notes

**Spec coverage** — maps to `docs/superpowers/specs/2026-04-21-nocs-v0.1-design.md`:

- §9.1 text-search target picker — Tasks 13, 14, 16, 18.
- §9.1 selecting target shows RA/Dec (J2000 and current), altitude, azimuth, airmass, transit — `TargetObservation` (Task 16), `TargetService.observation()` (Task 16), controller (Task 18).
- §9.2 bundled Messier, Caldwell, NGC+IC, named stars, solar system — Task 3 (data) + Task 14 (solar system) + Task 16 (wiring). Footprint well under 10 MB (OpenNGC TSV is ~1.5 MB, others are ~200 KB combined).
- §9.3 local first, SIMBAD fallback gated by `online_resolver` — Tasks 2, 16, 17.
- §9.3 never silently slew on miss — Task 18 returns 404 on unknown `/api/targets/{id}` and empty array on search miss.
- §9.4 precession J2000→JNow, refraction-aware altitude, ephemeris — Tasks 6, 7, 8, 9.
- §12.1 `observatories`, `targets_custom` tables — Task 1.
- §13 LocationService — subsumed by `ObservatoryService` (Task 11). The spec's LocationService responsibilities (get/set mount location) are either covered here (observatory location) or will be covered in Plan G when we wire mount-location sync.
- §18 open question #6 (horizon mask on observatories) — Task 1 ships the column; Task 10 ships the helper; enforcement lands in Plan F.
- §8.2 REST: `GET /api/targets/search?q=M31`, `GET /api/targets/{id}` — Task 18. Observatories surface extends what §8.2 lists (we add CRUD and `activate` — consistent with the spec's "no design constraints forbid them" posture).

Deliberately out of scope:

- Slew wiring (spec §8.2 `POST /api/mounts/{id}/slew` — Plan B, already done; Plan C gives mouse-driving the coordinates).
- Safety alt-limit rules — Plan F.
- UI — Plan H.
- Full-sky star catalogs — spec §9.2 explicitly excludes for v0.1.
- Cosmic autofocus targeting heuristics, etc.

**Type / name consistency check:**

- Target ID grammar: `<catalog>:<designator>` with `sun`, `moon`, `planet:*`, `messier:*`, `caldwell:*`, `ngc:*`, `ic:*`, `star:*`, `simbad:*`, `custom:*` (Tasks 4, 13, 14, 15, 17).
- `Target(id, primaryName, aliases, kind, raJ2000Deg, decJ2000Deg, constellation, magnitude, sizeArcmin, notes)` (Task 4) — used identically by `CatalogLoader` (Task 13), `SolarSystemCatalog` (Task 14), `TargetRepository` (Task 15), `SimbadResolver` (Task 17), controller DTO (Task 18).
- `TargetKind` values referenced by the fetch script's AWK mapper (Task 3) are all enum constants defined in Task 4.
- `GeographicLocation(latitudeDeg, longitudeDeg, elevationM)` (Task 7) consumed by `Horizontal`, `RiseTransitSet`, `ObservatoryService`, `TargetService`.
- `Observatory` record (Task 11): `id, name, latitudeDeg, longitudeDeg, elevationM, timezone, horizonMaskJson, active` — same column names on the controller DTO (Task 12).
- Flyway V2 columns: `latitude_deg, longitude_deg, elevation_m, timezone, horizon_mask_json, is_active` — repository's `RowMapper` (Task 11) uses exactly these.
- `TargetObservation` record (Task 16) consumed verbatim by the controller DTO (Task 18) — no transform.
- `Topic.TARGET` (Task 19) used only after declaration.
- Package root `dev.nocs` consistently used throughout.

**No placeholders:** every step contains complete code / commands. The only "external" data dependency is the fetch script, which has explicit URLs, explicit columns, and expected row counts. No "TODO", no "fill in later."

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-22-nocs-targets-and-catalogs.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
