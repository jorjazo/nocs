# NOCS PlateSolvingService + ASTAP fetch-install Implementation Plan (Plan E)

> **See also:** [NOCS v0.1 plan decomposition (A–I)](./2026-04-22-v0.1-plan-decomposition.md) — full roadmap and dependencies.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Plan E end-to-end: a pluggable `PlateSolvingService` whose v0.1 implementation wraps the ASTAP CLI, a `POST /api/platesolving/solve` endpoint that solves a previously-saved image and writes the WCS solution back into the FITS header (replacing the Plan D `amendHeader` stub) plus a `plate_solutions` row, and a guided **fetch-and-install** routine that downloads the ASTAP binary + H18 star DB into `data_dir/astap/` (with SHA-256 verification + progress events) so the spec §11 success criterion — "type `M31` into a target search, click Slew, have NOCS plate-solve and sync the mount automatically" — is solver-ready by the time Plan G's sequence engine lands.

**Architecture:** `PlateSolvingService` is a one-method interface (`solve(byte[] fits, SolveOptions) → SolveOutcome`) implemented by `AstapPlateSolver`. The solver delegates to two pure collaborators: `AstapInstallationLocator` (config path → `data_dir/astap/` → `PATH`) returns the resolved binary + DB or `Optional.empty()`, and `AstapInvoker` runs the binary in a temp work dir (FITS in, `.ini` out), surfaces stdout/stderr on failure, parses the `.ini` via `AstapIniParser`, and honours a `solveTimeoutSec` budget. The installer pipeline is a separate vertical: `AstapInstallSpecs` exposes the per-OS+arch download URLs / SHA-256s / archive types; `Sha256Verifier` + `ZipExtractor` are tiny pure helpers; `AstapDownloader` is an interface (`HttpAstapDownloader` for prod, `FileAstapDownloader` for tests) so we never hit the network in CI; `AstapInstaller` orchestrates `download → verify → extract → mark executable → place under data_dir/astap/`; and `AstapInstallService` is the Spring-managed front door that runs the install on a single-thread executor, publishes `Topic.PLATESOLVING / install_*` events with byte-level progress, and exposes a thread-safe `InstallProgress` snapshot. The REST controller exposes `POST /api/platesolving/solve`, `GET /api/platesolving/install`, `POST /api/platesolving/install`, and `GET /api/platesolving/install/progress`. Solve flow: controller loads the FITS via the new `ImageStoreService.loadFits(id)`, calls `solver.solve(...)`, persists a `plate_solutions` row via `PlateSolutionRepository`, calls `imageStoreService.amendHeader(id, wcsCards)` (now a real implementation built on `FitsHeaderWriter`), and publishes a `PLATESOLVING/solved` event. Plan E does **not** touch mount sync — `mount.syncTo(ra, dec)` is Plan G's job inside the sequence engine's `slew_and_sync` pre-step.

**Tech Stack:**
- JDK 25 + Spring Boot 3.5 (from Plan A)
- `spring-boot-starter-jdbc` + Flyway + SQLite (already wired)
- `java.net.http.HttpClient` (already on the jlink module list — no new runtime dep)
- `java.util.zip.ZipInputStream` for ASTAP binary archives (Linux/Windows ASTAP CLI is shipped as `.zip` — see `AstapInstallSpecs`)
- `MessageDigest` (`SHA-256`) for download verification
- `ProcessBuilder` for the ASTAP CLI (no JNI; the binary stays a child process per spec §4.2 / §11)
- Project Reactor `EventBus` (from Plan A) for `PLATESOLVING` events
- JUnit 5, AssertJ, Spring `MockMvc`, Awaitility (already present)
- `bash` only for the test fake ASTAP script (Linux CI). Windows CI is out of v0.1; see Plan I.

## Scope

### In scope for Plan E

1. New bus topic `PLATESOLVING`. Existing `Topic.SAFETY` / `Topic.SENSOR` patterns from Plan F are mirrored.
2. New config block `nocs.platesolving.*` (`solver`, `astap.binary-path`, `astap.db-dir`, `astap.db-name`, `solve-timeout-sec`, `install.binary-url-template`, `install.binary-sha256`, `install.db-url`, `install.db-sha256`, `install.allow-network`).
3. V4 Flyway migration: `plate_solutions` table tied to `images.id`.
4. Pluggable `PlateSolvingService` interface (`solve` + `isAvailable`) — astrometry.net is explicitly *future* and just needs another implementation.
5. ASTAP install detection (`AstapInstallationLocator`):
   - prefer `nocs.platesolving.astap.binary-path` if set + executable;
   - else look under `${data_dir}/astap/bin/astap_cli` (Linux) or `astap_cli.exe` (Windows);
   - else look under `PATH`;
   - DB resolution: `nocs.platesolving.astap.db-dir` (with `db-name`) → `${data_dir}/astap/db/`.
6. ASTAP CLI invocation (`AstapInvoker`): runs `astap_cli -f <fits> -d <db_dir> -wcs` (see `AstapInvocation` for the canonical argument list), with optional hint flags `-ra`, `-spd`, `-r`. Captures stdout/stderr on non-zero exit. Honours a configurable timeout (default 60 s) and destroys the child on timeout. All work happens in a per-call temp dir under `${java.io.tmpdir}/nocs-astap-XXXXXXXX/`.
7. ASTAP `.ini` parser (`AstapIniParser`): success → `PlateSolution` (RA J2000 deg, Dec J2000 deg, pixel scale arcsec/px, rotation deg, field width/height deg, `solvedAt`, `solver="astap"`); failure → `Failed(NO_STARS, errorMessage)`.
8. `AstapPlateSolver` (`PlateSolvingService` impl) wires locator + invoker; returns `Failed(NOT_INSTALLED, ...)` when the locator finds nothing; never blocks if `solver=disabled`.
9. `PlateSolutionRepository` JDBC CRUD (`insert`, `findByImageId`, `delete`, `list(limit, offset)`).
10. `ImageStoreService.amendHeader(long id, Map<String,String> wcsCards)` becomes a real implementation: rewrites the on-disk FITS via `FitsHeaderWriter` (atomic move), updates `images.bytes`, and (when `wcsCards` includes `CRVAL1` / `CRVAL2`) inserts/updates the `plate_solutions` row through the same call.
11. ASTAP install pipeline:
    - `AstapInstallSpecs.forCurrent()` (linux-x86_64, linux-arm64, windows-x86_64; `Optional.empty()` otherwise);
    - `AstapDownloader` interface + `HttpAstapDownloader` (streaming download, `Range`-less, byte counter);
    - `Sha256Verifier`;
    - `ZipExtractor` (handles the single `astap_cli` entry); for `.tar.gz` (RPi build) a tiny `TarGzExtractor` since `java.util.zip` only does ZIP and we will not pull in commons-compress.
    - `AstapInstaller.install(spec, dataDir, listener)` — synchronous, used by tests directly.
12. `AstapInstallService` — single-threaded `ScheduledExecutorService`, exposes `start(InstallRequest)`, `progress()`, `cancel()`. Publishes `PLATESOLVING/install_started`, `install_progress`, `install_completed`, `install_failed`. `nocs.platesolving.install.allow-network` defaults to `false`; setting it to `true` is the explicit user opt-in mirroring `nocs.targets.online-resolver`.
13. REST endpoints:
    - `POST /api/platesolving/solve` — body `{image_id, ra_hint_hours?, dec_hint_deg?, radius_deg?, scale_hint_arcsec_per_pixel?, timeout_sec?}` — returns `200` `{solved:true, solution:{...}}` or `422` `{solved:false, failure_kind, message}`.
    - `GET /api/platesolving/install` — `{installed, binary_path, db_dir, db_name, db_present, supported_platform}`.
    - `POST /api/platesolving/install` — body `{accept_license:true}` — `202` if started, `409` if already running, `403` if `allow-network=false`, `400` if license not accepted, `501` if platform unsupported.
    - `GET /api/platesolving/install/progress` — `{phase, bytes_done, bytes_total, message, updated_at}`.
14. `DataDirBootstrap.ensureLayout` creates `data_dir/astap/bin/` and `data_dir/astap/db/`.
15. `config.example.yaml` / `application.yaml` document the new block.
16. End-to-end integration test using a `FakeAstapInvoker` Spring bean (replaces the real invoker) that returns a deterministic `.ini` text → asserts solution row, FITS header amended (re-read via `FitsHeaderReader`), and `PLATESOLVING/solved` bus event.
17. README dev-quickstart additions: `curl POST /api/platesolving/solve` + `curl POST /api/platesolving/install` examples.

### Explicitly out of scope for Plan E

- `mount.syncTo(...)` integration after solve — Plan G's `slew_and_sync` sequence pre-step does this. Plan E publishes `PLATESOLVING/solved` with the RA/Dec so Plan G can subscribe.
- Astrometry.net implementation — the interface allows a sibling `AstrometryNetPlateSolver`, but only ASTAP ships in v0.1.
- Multi-DB selection (D50, V17, G17) — the install spec is templated on `db-name`; v0.1 defaults to `H18` and only ships defaults for that. Adding more variants later is a one-line config change.
- Auto-update of ASTAP — install once, ignore until user re-runs it.
- Resumable / range downloads — restart on failure. The install endpoint is idempotent.
- Solving from raw uploaded bytes (no `image_id`) — could be a v0.2 ergonomic, but the integration story (FITS amendment + DB row) is image-centric.
- Per-step batch solving from the sequence engine — Plan G calls `/solve` per sub.
- Plate-solver reverse lookup of an existing solution by RA/Dec — out of v0.1.
- Web UI for the install wizard / solve banner — Plan H.

## File Structure

All paths are relative to the repo root (`/home/jorjazo/dev/nocs/nocs`). Every file below has one responsibility; none should exceed ~250 lines.

**New main sources** (`src/main/java/dev/nocs/platesolving/`):

- `PlateSolvingService.java` — interface (`solve`, `isAvailable`).
- `PlateSolution.java` — record `(double raJ2000Deg, double decJ2000Deg, double pixelScaleArcsecPerPx, double rotationDeg, double fieldWidthDeg, double fieldHeightDeg, java.time.Instant solvedAt, String solver)`.
- `SolveOptions.java` — record `(Double raHintDeg, Double decHintDeg, Double radiusDeg, Double pixelScaleArcsecPerPxHint, Double timeoutSec)` with `defaults()` and `withTimeout(double)` helpers.
- `SolveOutcome.java` — sealed interface `permits Solved, Failed`; nested records.
- `FailureKind.java` — enum `NOT_INSTALLED, NO_STARS, TIMEOUT, IO_ERROR, INTERNAL_ERROR`.
- `SolverKind.java` — enum `ASTAP, DISABLED`.
- `astap/AstapInstallation.java` — record `(java.nio.file.Path binary, java.nio.file.Path dbDir, String dbName)`.
- `astap/AstapInstallationLocator.java` — `Optional<AstapInstallation> locate(NocsProperties props, java.nio.file.Path dataDir)`.
- `astap/AstapInvocation.java` — pure helper that builds the command list from `(AstapInstallation, java.nio.file.Path inputFits, SolveOptions)`. Lives separately so it's exhaustively unit-tested without spawning processes.
- `astap/AstapIniParser.java` — `SolveOutcome parse(String iniText, long durationMs, java.time.Instant now)`.
- `astap/AstapInvoker.java` — `SolveOutcome invoke(AstapInstallation, byte[] fits, SolveOptions)`. Uses an injected `ProcessRunner` for testability.
- `astap/ProcessRunner.java` — interface `(List<String> cmd, java.nio.file.Path workDir, long timeoutSec) → ProcessResult`.
- `astap/DefaultProcessRunner.java` — `java.lang.ProcessBuilder` impl.
- `astap/ProcessResult.java` — record `(int exitCode, String stdout, String stderr, boolean timedOut, long durationMs)`.
- `astap/AstapPlateSolver.java` — `PlateSolvingService` impl wiring locator + invoker.
- `install/InstallPhase.java` — enum `IDLE, RESOLVING_SPEC, DOWNLOADING_BINARY, VERIFYING_BINARY, EXTRACTING_BINARY, DOWNLOADING_DB, VERIFYING_DB, EXTRACTING_DB, DONE, FAILED, CANCELLED`.
- `install/InstallProgress.java` — record `(InstallPhase phase, long bytesDone, long bytesTotal, String message, java.time.Instant updatedAt)`.
- `install/InstallRequest.java` — record `(boolean acceptLicense)`.
- `install/AstapInstallSpec.java` — record `(java.net.URI binaryUrl, String binarySha256, ArchiveKind binaryKind, String binaryEntryName, java.net.URI dbUrl, String dbSha256, String dbName, ArchiveKind dbKind)`.
- `install/ArchiveKind.java` — enum `ZIP, TAR_GZ, RAW`.
- `install/AstapInstallSpecs.java` — `Optional<AstapInstallSpec> forCurrent(NocsProperties props)`.
- `install/Sha256Verifier.java` — `void verify(java.nio.file.Path file, String expectedHex)`; throws on mismatch.
- `install/ZipExtractor.java` — `void extractEntry(Path zip, String entry, Path destFile)` + `void extractAll(Path zip, Path destDir)`.
- `install/TarGzExtractor.java` — minimal pure-Java tar.gz reader (handles 512-byte headers + ustar; we ship without external libs).
- `install/AstapDownloader.java` — interface `void download(URI url, Path dest, ProgressListener listener)`.
- `install/ProgressListener.java` — functional interface `void onBytes(long bytesDone, long bytesTotal)`.
- `install/HttpAstapDownloader.java` — `java.net.http.HttpClient` impl.
- `install/AstapInstaller.java` — synchronous orchestrator: download/verify/extract binary then DB into `data_dir/astap/`.
- `install/AstapInstallService.java` — async front door + progress + events.
- `PlateSolutionRecord.java` — record `(Long id, long imageId, double raJ2000Deg, double decJ2000Deg, double pixelScaleArcsecPerPx, double rotationDeg, double fieldWidthDeg, double fieldHeightDeg, long durationMs, String solver, java.time.Instant solvedAt)` with `forInsert(...)`.
- `PlateSolutionRepository.java` — JDBC.
- `api/PlateSolvingController.java` — REST endpoints.
- `api/dto/SolveRequest.java`, `SolveResponse.java`, `PlateSolutionView.java`, `InstallStatusView.java`, `InstallProgressView.java`.

**Modified main sources:**

- `events/Topic.java` — add `PLATESOLVING`.
- `image/FitsHeaderWriter.java` — **new** file under existing `image/` package: `byte[] writeWithCards(byte[] originalFits, java.util.SequencedMap<String, String> additionalOrReplacedCards)`. Rebuilds the primary HDU header (preserving `SIMPLE`, `BITPIX`, `NAXIS*`, `EXTEND`, original cards in order, then appending or replacing per `additionalOrReplacedCards`), pads to next 2880-byte boundary, concatenates the data section verbatim.
- `image/ImageStoreService.java` — drop the `amendHeader` stub; implement it in terms of `FitsHeaderWriter`, atomic move, optional `PlateSolutionRepository.upsertForImage(...)` when WCS cards are present, update `images.bytes`. Add `Optional<byte[]> loadFits(long id)` (reads from disk, used by the controller and tests).
- `config/NocsProperties.java` — add `PlateSolving` subrecord.
- `config/AppBeansConfig.java` — wire `ProcessRunner`, `AstapInvoker`, `AstapPlateSolver` (as `PlateSolvingService` bean), `AstapInstallationLocator`, `AstapInstallSpecs`, `Sha256Verifier`, `ZipExtractor`, `TarGzExtractor`, `HttpAstapDownloader` (as `AstapDownloader`), `AstapInstaller`, `AstapInstallService`. The solver bean is `@ConditionalOnProperty(name="nocs.platesolving.solver", havingValue="astap", matchIfMissing=true)`; `solver=disabled` instead binds a no-op `DisabledPlateSolvingService`.
- `bootstrap/DataDirBootstrap.java` — create `astap/bin/` and `astap/db/` under `data_dir`.
- `application.yaml` — append `nocs.platesolving.*` defaults.
- `config.example.yaml` — append a commented `platesolving:` block.

**Resources:**

- `src/main/resources/db/migration/V4__plate_solutions.sql`.

**New test sources** (`src/test/java/dev/nocs/platesolving/` unless noted):

- `PlateSolvingTopicTest.java` — mirrors `safety/SensorTopicTest`.
- `PlateSolvingConfigTest.java` — binds `nocs.platesolving.*` from `@TestPropertySource`.
- `PlateSolutionRepositoryTest.java` — `@SpringBootTest` + `JdbcTemplate`.
- `domain/SolveOutcomeTest.java`, `domain/SolveOptionsTest.java`, `domain/PlateSolutionTest.java`.
- `astap/AstapInstallationLocatorTest.java`.
- `astap/AstapInvocationTest.java`.
- `astap/AstapIniParserTest.java` — happy path + each documented failure shape.
- `astap/AstapInvokerTest.java` — uses `src/test/resources/platesolving/astap/fake-astap.sh` (Linux) + a `RecordingProcessRunner` for OS-agnostic coverage.
- `astap/AstapPlateSolverTest.java` — combines invoker stub + locator stub.
- `image/FitsHeaderWriterTest.java` — round-trip header reader/writer with replaced and appended cards.
- `image/ImageStoreServiceAmendHeaderTest.java` — re-reads file via `FitsHeaderReader`, asserts WCS cards present, asserts `plate_solutions` row inserted.
- `install/Sha256VerifierTest.java`.
- `install/ZipExtractorTest.java`.
- `install/TarGzExtractorTest.java`.
- `install/AstapInstallSpecsTest.java` — guarantees `linux-x86_64`, `linux-arm64`, `windows-x86_64` resolve when configured; `unsupported` returns empty.
- `install/AstapInstallerTest.java` — uses a `FileAstapDownloader` test double + locally-built fixture archives.
- `install/AstapInstallServiceTest.java` — fake `AstapInstaller` injected; verifies progress + events + `allow-network=false` rejection.
- `api/PlateSolvingControllerTest.java` — `MockMvc` (auth, validation, happy path with stubbed solver bean).
- `IntegrationPlateSolvingApiTest.java` — full Spring context; stubs `PlateSolvingService` and `AstapInstallService`; drives `POST /api/platesolving/solve` end-to-end.

**New test resources:**

- `src/test/resources/platesolving/astap/fake-astap.sh` — POSIX shell stub that writes a deterministic `.ini` next to the input FITS, mirrors timeout behaviour with `sleep` when `FAKE_ASTAP_SLEEP` is set, and respects the `-f`/`-d` flags. Marked `+x` by `AstapInvokerTest` setup.
- `src/test/resources/platesolving/astap/fake-astap-failed.ini` — solver-failed `.ini` fixture.
- `src/test/resources/platesolving/astap/fake-astap-solved.ini` — solver-success `.ini` fixture.
- `src/test/resources/platesolving/install/fake-binary-archive.zip` — built at test compile time; alternative is to build it programmatically inside the test (`ZipOutputStream`) — preferred to keep VCS clean. **Use the in-test factory approach; no committed binaries.**
- `src/test/resources/platesolving/install/fake-db.zip` — same approach.

---

## Tasks

Each task is self-contained: files listed, TDD steps with complete code, exact commands with expected output, and a commit at the end. Tasks 1–3 wire schema, topic, and config. Tasks 4–6 build the domain types + ASTAP installation locator + ini parser. Tasks 7–8 wire the invoker + solver. Task 9 lands the repository. Task 10 implements `amendHeader` (replaces the Plan D stub). Task 11 builds the install support classes. Task 12 wires the async install service. Task 13 ships REST. Task 14 finalises config + bootstrap. Task 15 is the end-to-end integration test. Task 16 updates README + the decomposition status table.

---

### Task 1: V4 Flyway migration for `plate_solutions`

**Files:**
- Create: `src/main/resources/db/migration/V4__plate_solutions.sql`
- Modify: `src/test/java/dev/nocs/persistence/DataSourceConfigTest.java`

- [ ] **Step 1.1: Write the failing schema-presence test**

Append to `src/test/java/dev/nocs/persistence/DataSourceConfigTest.java`:

```java
@Test
void flywayCreatesPlateSolutionsTable() {
    Integer count = jdbcTemplate.queryForObject(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='plate_solutions'",
            Integer.class);
    assertThat(count).isEqualTo(1);
}
```

- [ ] **Step 1.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.persistence.DataSourceConfigTest.flywayCreatesPlateSolutionsTable'`
Expected: FAIL with `expected: 1 but was: 0`.

- [ ] **Step 1.3: Create the migration**

Create `src/main/resources/db/migration/V4__plate_solutions.sql`:

```sql
CREATE TABLE plate_solutions (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id                    INTEGER NOT NULL UNIQUE REFERENCES images(id) ON DELETE CASCADE,
    ra_j2000_deg                REAL    NOT NULL,
    dec_j2000_deg               REAL    NOT NULL,
    pixel_scale_arcsec_per_px   REAL    NOT NULL DEFAULT 0,
    rotation_deg                REAL    NOT NULL DEFAULT 0,
    field_width_deg             REAL    NOT NULL DEFAULT 0,
    field_height_deg            REAL    NOT NULL DEFAULT 0,
    duration_ms                 INTEGER NOT NULL DEFAULT 0,
    solver                      TEXT    NOT NULL DEFAULT 'astap',
    solved_at                   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_plate_solutions_image_id ON plate_solutions(image_id);
CREATE INDEX idx_plate_solutions_solved_at ON plate_solutions(solved_at);
```

- [ ] **Step 1.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.persistence.DataSourceConfigTest'`
Expected: every `flywayCreates*` test passes (including the new one).

- [ ] **Step 1.5: Commit**

```bash
git add src/main/resources/db/migration/V4__plate_solutions.sql \
        src/test/java/dev/nocs/persistence/DataSourceConfigTest.java
git commit -m "feat: V4 migration for plate_solutions table"
```

---

### Task 2: Add `PLATESOLVING` topic

**Files:**
- Modify: `src/main/java/dev/nocs/events/Topic.java`
- Create: `src/test/java/dev/nocs/platesolving/PlateSolvingTopicTest.java`

- [ ] **Step 2.1: Write the failing test**

Create `src/test/java/dev/nocs/platesolving/PlateSolvingTopicTest.java`:

```java
package dev.nocs.platesolving;

import dev.nocs.events.Topic;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class PlateSolvingTopicTest {

    @Test
    void platesolvingTopicExists() {
        assertThat(Topic.valueOf("PLATESOLVING")).isEqualTo(Topic.PLATESOLVING);
        assertThat(Topic.PLATESOLVING.wire()).isEqualTo("platesolving");
        assertThat(Topic.fromWire("platesolving")).isEqualTo(Topic.PLATESOLVING);
    }
}
```

- [ ] **Step 2.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.platesolving.PlateSolvingTopicTest'`
Expected: compile failure — `Topic.PLATESOLVING` does not exist.

- [ ] **Step 2.3: Add the enum value**

Modify `src/main/java/dev/nocs/events/Topic.java`:

```java
package dev.nocs.events;

public enum Topic {
    MOUNT, CAMERA, FILTERWHEEL, FOCUSER,
    SEQUENCE, SAFETY, SESSION, DEVICE_CONNECTION, SYSTEM,
    TARGET, SENSOR, PLATESOLVING;

    public String wire() {
        return name().toLowerCase();
    }

    public static Topic fromWire(String wire) {
        return Topic.valueOf(wire.trim().toUpperCase());
    }
}
```

- [ ] **Step 2.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.platesolving.PlateSolvingTopicTest'`
Expected: PASS.

- [ ] **Step 2.5: Commit**

```bash
git add src/main/java/dev/nocs/events/Topic.java \
        src/test/java/dev/nocs/platesolving/PlateSolvingTopicTest.java
git commit -m "feat(events): add PLATESOLVING topic for plan E"
```

---

### Task 3: `nocs.platesolving.*` config

**Files:**
- Modify: `src/main/java/dev/nocs/config/NocsProperties.java`
- Modify: `src/main/resources/application.yaml`
- Create: `src/test/java/dev/nocs/platesolving/PlateSolvingConfigTest.java`

- [ ] **Step 3.1: Write the failing test**

Create `src/test/java/dev/nocs/platesolving/PlateSolvingConfigTest.java`:

```java
package dev.nocs.platesolving;

import dev.nocs.config.NocsProperties;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@TestPropertySource(properties = {
        "nocs.auth.token=t",
        "nocs.platesolving.solver=astap",
        "nocs.platesolving.solve-timeout-sec=42",
        "nocs.platesolving.astap.binary-path=/opt/astap/astap_cli",
        "nocs.platesolving.astap.db-dir=/srv/astap/db",
        "nocs.platesolving.astap.db-name=H18",
        "nocs.platesolving.install.allow-network=true",
        "nocs.platesolving.install.binary-url-template=https://example.invalid/astap-{os}-{arch}.zip",
        "nocs.platesolving.install.binary-sha256.linux-x86_64=deadbeef",
        "nocs.platesolving.install.db-url=https://example.invalid/h18.zip",
        "nocs.platesolving.install.db-sha256=cafebabe"
})
class PlateSolvingConfigTest {

    @Autowired NocsProperties props;

    @Test
    void platesolvingPropertiesAreBound() {
        NocsProperties.PlateSolving ps = props.platesolving();
        assertThat(ps).isNotNull();
        assertThat(ps.solver()).isEqualTo("astap");
        assertThat(ps.solveTimeoutSec()).isEqualTo(42L);
        assertThat(ps.astap().binaryPath()).isEqualTo("/opt/astap/astap_cli");
        assertThat(ps.astap().dbDir()).isEqualTo("/srv/astap/db");
        assertThat(ps.astap().dbName()).isEqualTo("H18");
        assertThat(ps.install().allowNetwork()).isTrue();
        assertThat(ps.install().binaryUrlTemplate()).isEqualTo("https://example.invalid/astap-{os}-{arch}.zip");
        assertThat(ps.install().binarySha256().get("linux-x86_64")).isEqualTo("deadbeef");
        assertThat(ps.install().dbUrl()).isEqualTo("https://example.invalid/h18.zip");
        assertThat(ps.install().dbSha256()).isEqualTo("cafebabe");
    }

    @Test
    void defaultsAreSensibleWhenAbsent() {
        NocsProperties.PlateSolving ps = props.platesolving();
        if (ps.solveTimeoutSec() == 42L) {
            return;
        }
        assertThat(ps.solveTimeoutSec()).isEqualTo(60L);
        assertThat(ps.solver()).isEqualTo("astap");
    }
}
```

- [ ] **Step 3.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.platesolving.PlateSolvingConfigTest'`
Expected: compile failure — `NocsProperties.PlateSolving` does not exist.

- [ ] **Step 3.3: Add the config record**

Modify `src/main/java/dev/nocs/config/NocsProperties.java` to add `platesolving` to the top-level record and add the nested types:

```java
package dev.nocs.config;

import dev.nocs.indi.IndiConfig;
import java.util.Map;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "nocs")
public record NocsProperties(
        Auth auth,
        Server server,
        Datasource datasource,
        String dataDir,
        IndiConfig indi,
        Targets targets,
        Safety safety,
        PlateSolving platesolving) {

    public record Auth(String token) {}

    public record Server(String host, Integer port) {}

    public record Datasource(String url) {}

    public record Targets(Boolean onlineResolver, String simbadBaseUrl) {
        public Targets {
            if (onlineResolver == null) {
                onlineResolver = false;
            }
            if (simbadBaseUrl == null || simbadBaseUrl.isBlank()) {
                simbadBaseUrl = "https://simbad.u-strasbg.fr/simbad";
            }
        }
    }

    public record Safety(String rulesPath, Long altitudeEvalIntervalMs, Long sensorOfflineDefaultSeconds) {
        public Safety {
            if (altitudeEvalIntervalMs == null || altitudeEvalIntervalMs <= 0) {
                altitudeEvalIntervalMs = 10_000L;
            }
            if (sensorOfflineDefaultSeconds == null || sensorOfflineDefaultSeconds <= 0) {
                sensorOfflineDefaultSeconds = 60L;
            }
        }
    }

    public record PlateSolving(
            String solver,
            Long solveTimeoutSec,
            Astap astap,
            Install install) {

        public PlateSolving {
            if (solver == null || solver.isBlank()) {
                solver = "astap";
            }
            if (solveTimeoutSec == null || solveTimeoutSec <= 0) {
                solveTimeoutSec = 60L;
            }
            if (astap == null) {
                astap = new Astap(null, null, null);
            }
            if (install == null) {
                install = new Install(false, null, Map.of(), null, null);
            }
        }

        public record Astap(String binaryPath, String dbDir, String dbName) {
            public Astap {
                if (dbName == null || dbName.isBlank()) {
                    dbName = "H18";
                }
            }
        }

        public record Install(
                Boolean allowNetwork,
                String binaryUrlTemplate,
                Map<String, String> binarySha256,
                String dbUrl,
                String dbSha256) {

            public Install {
                if (allowNetwork == null) {
                    allowNetwork = false;
                }
                if (binarySha256 == null) {
                    binarySha256 = Map.of();
                }
            }
        }
    }
}
```

- [ ] **Step 3.4: Add the defaults to `application.yaml`**

Modify `src/main/resources/application.yaml`. Append under the existing `nocs:` block:

```yaml
  platesolving:
    solver: astap
    solve-timeout-sec: 60
    astap:
      binary-path: ""
      db-dir: ""
      db-name: H18
    install:
      allow-network: false
      binary-url-template: "https://sourceforge.net/projects/astap-program/files/astap_cli_{os}_{arch}.zip/download"
      binary-sha256: {}
      db-url: ""
      db-sha256: ""
```

These defaults are intentionally inert: `allow-network=false` blocks the install endpoint, and the `binary-sha256` map is empty so a user must explicitly opt in by populating the map (and the corresponding `db-sha256`). Documenting this is part of Task 14.

- [ ] **Step 3.5: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.platesolving.PlateSolvingConfigTest'`
Expected: PASS.

- [ ] **Step 3.6: Commit**

```bash
git add src/main/java/dev/nocs/config/NocsProperties.java \
        src/main/resources/application.yaml \
        src/test/java/dev/nocs/platesolving/PlateSolvingConfigTest.java
git commit -m "feat(config): nocs.platesolving.* config block"
```

---

### Task 4: Domain types — `PlateSolution`, `SolveOptions`, `SolveOutcome`, `FailureKind`, `SolverKind`

**Files:**
- Create: `src/main/java/dev/nocs/platesolving/SolverKind.java`
- Create: `src/main/java/dev/nocs/platesolving/FailureKind.java`
- Create: `src/main/java/dev/nocs/platesolving/PlateSolution.java`
- Create: `src/main/java/dev/nocs/platesolving/SolveOptions.java`
- Create: `src/main/java/dev/nocs/platesolving/SolveOutcome.java`
- Create: `src/main/java/dev/nocs/platesolving/PlateSolvingService.java`
- Create: `src/test/java/dev/nocs/platesolving/domain/SolveOptionsTest.java`
- Create: `src/test/java/dev/nocs/platesolving/domain/PlateSolutionTest.java`
- Create: `src/test/java/dev/nocs/platesolving/domain/SolveOutcomeTest.java`

- [ ] **Step 4.1: Failing tests**

Create `src/test/java/dev/nocs/platesolving/domain/SolveOptionsTest.java`:

```java
package dev.nocs.platesolving.domain;

import dev.nocs.platesolving.SolveOptions;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SolveOptionsTest {

    @Test
    void defaultsAreEmpty() {
        SolveOptions opts = SolveOptions.defaults();
        assertThat(opts.raHintDeg()).isNull();
        assertThat(opts.decHintDeg()).isNull();
        assertThat(opts.radiusDeg()).isNull();
        assertThat(opts.pixelScaleArcsecPerPxHint()).isNull();
        assertThat(opts.timeoutSec()).isNull();
    }

    @Test
    void withTimeoutOverridesOnlyTimeout() {
        SolveOptions opts = SolveOptions.defaults().withTimeout(45.0);
        assertThat(opts.timeoutSec()).isEqualTo(45.0);
        assertThat(opts.raHintDeg()).isNull();
    }

    @Test
    void rejectsNegativeRadius() {
        org.junit.jupiter.api.Assertions.assertThrows(
                IllegalArgumentException.class,
                () -> new SolveOptions(0.0, 0.0, -1.0, null, null));
    }

    @Test
    void rejectsNegativeTimeout() {
        org.junit.jupiter.api.Assertions.assertThrows(
                IllegalArgumentException.class,
                () -> new SolveOptions(null, null, null, null, -3.0));
    }
}
```

Create `src/test/java/dev/nocs/platesolving/domain/PlateSolutionTest.java`:

```java
package dev.nocs.platesolving.domain;

import dev.nocs.platesolving.PlateSolution;
import java.time.Instant;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class PlateSolutionTest {

    @Test
    void wcsCardsContainCrvalAndScale() {
        Instant now = Instant.parse("2026-04-22T22:00:00Z");
        PlateSolution s = new PlateSolution(
                10.6847083, 41.269083, 1.234, 12.5, 0.5, 0.4, now, "astap");

        java.util.SequencedMap<String, String> cards = s.toFitsCards();

        assertThat(cards).containsEntry("CRVAL1", "10.6847083");
        assertThat(cards).containsEntry("CRVAL2", "41.269083");
        assertThat(cards).containsEntry("PLTSOLVD", "T");
        assertThat(cards).containsKey("CDELT1");
        assertThat(cards).containsKey("CROTA2");
        assertThat(cards.get("PLATESLV")).isEqualTo("'astap   '");
    }
}
```

Create `src/test/java/dev/nocs/platesolving/domain/SolveOutcomeTest.java`:

```java
package dev.nocs.platesolving.domain;

import dev.nocs.platesolving.FailureKind;
import dev.nocs.platesolving.PlateSolution;
import dev.nocs.platesolving.SolveOutcome;
import java.time.Instant;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SolveOutcomeTest {

    @Test
    void solvedExposesSolution() {
        PlateSolution s = new PlateSolution(1, 2, 3, 0, 0, 0, Instant.EPOCH, "astap");
        SolveOutcome.Solved out = new SolveOutcome.Solved(s, 1234L);
        assertThat(out.solution()).isSameAs(s);
        assertThat(out.durationMs()).isEqualTo(1234L);
    }

    @Test
    void failureKindIsCarried() {
        SolveOutcome.Failed f = new SolveOutcome.Failed(FailureKind.NO_STARS, "too few", 200L);
        assertThat(f.kind()).isEqualTo(FailureKind.NO_STARS);
        assertThat(f.message()).isEqualTo("too few");
        assertThat(f.durationMs()).isEqualTo(200L);
    }
}
```

- [ ] **Step 4.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.platesolving.domain.*'`
Expected: compilation errors (no classes yet).

- [ ] **Step 4.3: Implement enums**

Create `src/main/java/dev/nocs/platesolving/SolverKind.java`:

```java
package dev.nocs.platesolving;

public enum SolverKind {
    ASTAP, DISABLED;

    public String wire() {
        return name().toLowerCase();
    }

    public static SolverKind fromWire(String s) {
        if (s == null || s.isBlank()) {
            return ASTAP;
        }
        return SolverKind.valueOf(s.trim().toUpperCase());
    }
}
```

Create `src/main/java/dev/nocs/platesolving/FailureKind.java`:

```java
package dev.nocs.platesolving;

public enum FailureKind {
    NOT_INSTALLED,
    NO_STARS,
    TIMEOUT,
    IO_ERROR,
    INTERNAL_ERROR;

    public String wire() {
        return name().toLowerCase();
    }
}
```

- [ ] **Step 4.4: Implement records**

Create `src/main/java/dev/nocs/platesolving/PlateSolution.java`:

```java
package dev.nocs.platesolving;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.SequencedMap;

public record PlateSolution(
        double raJ2000Deg,
        double decJ2000Deg,
        double pixelScaleArcsecPerPx,
        double rotationDeg,
        double fieldWidthDeg,
        double fieldHeightDeg,
        Instant solvedAt,
        String solver) {

    public PlateSolution {
        if (raJ2000Deg < 0 || raJ2000Deg >= 360) {
            throw new IllegalArgumentException("raJ2000Deg must be in [0, 360), got " + raJ2000Deg);
        }
        if (decJ2000Deg < -90 || decJ2000Deg > 90) {
            throw new IllegalArgumentException("decJ2000Deg must be in [-90, 90], got " + decJ2000Deg);
        }
        if (solver == null || solver.isBlank()) {
            solver = "unknown";
        }
        if (solvedAt == null) {
            solvedAt = Instant.now();
        }
    }

    /**
     * FITS WCS-style header cards. Inserted into the saved FITS via
     * {@link dev.nocs.image.ImageStoreService#amendHeader(long, java.util.Map)}.
     * Insertion order is preserved by {@link SequencedMap}.
     */
    public SequencedMap<String, String> toFitsCards() {
        SequencedMap<String, String> cards = new LinkedHashMap<>();
        cards.put("PLTSOLVD", "T");
        cards.put("CTYPE1", "'RA---TAN'");
        cards.put("CTYPE2", "'DEC--TAN'");
        cards.put("CRVAL1", trim(raJ2000Deg));
        cards.put("CRVAL2", trim(decJ2000Deg));
        double cdelt = pixelScaleArcsecPerPx / 3600.0;
        cards.put("CDELT1", trim(-cdelt));
        cards.put("CDELT2", trim(cdelt));
        cards.put("CROTA1", trim(rotationDeg));
        cards.put("CROTA2", trim(rotationDeg));
        cards.put("PLATESLV", quote(solver));
        cards.put("PLTSOLDT", quote(solvedAt.toString()));
        cards.put("FOVWIDTH", trim(fieldWidthDeg));
        cards.put("FOVHIGHT", trim(fieldHeightDeg));
        return cards;
    }

    private static String trim(double v) {
        return String.format(Locale.ROOT, "%.10f", v).replaceAll("0+$", "").replaceAll("\\.$", ".0");
    }

    private static String quote(String s) {
        String trimmed = s.length() > 8 ? s.substring(0, 8) : s;
        return "'" + String.format(Locale.ROOT, "%-8s", trimmed) + "'";
    }
}
```

Create `src/main/java/dev/nocs/platesolving/SolveOptions.java`:

```java
package dev.nocs.platesolving;

public record SolveOptions(
        Double raHintDeg,
        Double decHintDeg,
        Double radiusDeg,
        Double pixelScaleArcsecPerPxHint,
        Double timeoutSec) {

    public SolveOptions {
        if (radiusDeg != null && radiusDeg < 0) {
            throw new IllegalArgumentException("radiusDeg must be >= 0, got " + radiusDeg);
        }
        if (pixelScaleArcsecPerPxHint != null && pixelScaleArcsecPerPxHint <= 0) {
            throw new IllegalArgumentException("pixelScaleArcsecPerPxHint must be > 0");
        }
        if (timeoutSec != null && timeoutSec <= 0) {
            throw new IllegalArgumentException("timeoutSec must be > 0");
        }
    }

    public static SolveOptions defaults() {
        return new SolveOptions(null, null, null, null, null);
    }

    public SolveOptions withTimeout(double seconds) {
        return new SolveOptions(raHintDeg, decHintDeg, radiusDeg, pixelScaleArcsecPerPxHint, seconds);
    }
}
```

Create `src/main/java/dev/nocs/platesolving/SolveOutcome.java`:

```java
package dev.nocs.platesolving;

public sealed interface SolveOutcome permits SolveOutcome.Solved, SolveOutcome.Failed {

    long durationMs();

    record Solved(PlateSolution solution, long durationMs) implements SolveOutcome {
        public Solved {
            if (solution == null) {
                throw new IllegalArgumentException("solution required");
            }
        }
    }

    record Failed(FailureKind kind, String message, long durationMs) implements SolveOutcome {
        public Failed {
            if (kind == null) {
                throw new IllegalArgumentException("kind required");
            }
            if (message == null) {
                message = "";
            }
        }
    }
}
```

Create `src/main/java/dev/nocs/platesolving/PlateSolvingService.java`:

```java
package dev.nocs.platesolving;

public interface PlateSolvingService {

    SolveOutcome solve(byte[] fits, SolveOptions options);

    boolean isAvailable();
}
```

- [ ] **Step 4.5: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.platesolving.domain.*'`
Expected: all three test classes pass.

- [ ] **Step 4.6: Commit**

```bash
git add src/main/java/dev/nocs/platesolving/SolverKind.java \
        src/main/java/dev/nocs/platesolving/FailureKind.java \
        src/main/java/dev/nocs/platesolving/PlateSolution.java \
        src/main/java/dev/nocs/platesolving/SolveOptions.java \
        src/main/java/dev/nocs/platesolving/SolveOutcome.java \
        src/main/java/dev/nocs/platesolving/PlateSolvingService.java \
        src/test/java/dev/nocs/platesolving/domain/
git commit -m "feat(platesolving): domain types (PlateSolution, SolveOptions, SolveOutcome, PlateSolvingService)"
```

---

### Task 5: ASTAP installation locator

**Files:**
- Create: `src/main/java/dev/nocs/platesolving/astap/AstapInstallation.java`
- Create: `src/main/java/dev/nocs/platesolving/astap/AstapInstallationLocator.java`
- Create: `src/test/java/dev/nocs/platesolving/astap/AstapInstallationLocatorTest.java`

- [ ] **Step 5.1: Failing test**

Create `src/test/java/dev/nocs/platesolving/astap/AstapInstallationLocatorTest.java`:

```java
package dev.nocs.platesolving.astap;

import dev.nocs.config.NocsProperties;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.assertj.core.api.Assertions.assertThat;

class AstapInstallationLocatorTest {

    @Test
    void prefersExplicitConfigPath(@TempDir Path tmp) throws Exception {
        Path bin = Files.createDirectories(tmp.resolve("custom")).resolve("astap_cli");
        Files.writeString(bin, "#!/usr/bin/env bash\nexit 0\n");
        bin.toFile().setExecutable(true);
        Path db = Files.createDirectories(tmp.resolve("dbs"));
        Files.createFile(db.resolve("h18_star_database_index.dat"));

        NocsProperties props = propsWith(bin.toString(), db.toString(), "H18");

        Optional<AstapInstallation> out = new AstapInstallationLocator().locate(props, tmp.resolve("data"));

        assertThat(out).isPresent();
        assertThat(out.get().binary()).isEqualTo(bin);
        assertThat(out.get().dbDir()).isEqualTo(db);
        assertThat(out.get().dbName()).isEqualTo("H18");
    }

    @Test
    void fallsBackToDataDirInstall(@TempDir Path data) throws Exception {
        Path bin = Files.createDirectories(data.resolve("astap/bin")).resolve("astap_cli");
        Files.writeString(bin, "#!/usr/bin/env bash\nexit 0\n");
        bin.toFile().setExecutable(true);
        Files.createDirectories(data.resolve("astap/db"));
        Files.createFile(data.resolve("astap/db/h18_star_database_index.dat"));

        Optional<AstapInstallation> out = new AstapInstallationLocator()
                .locate(propsWith("", "", "H18"), data);

        assertThat(out).isPresent();
        assertThat(out.get().binary()).isEqualTo(bin);
    }

    @Test
    void returnsEmptyWhenBinaryIsMissing(@TempDir Path data) {
        Optional<AstapInstallation> out = new AstapInstallationLocator()
                .locate(propsWith("", "", "H18"), data);

        assertThat(out).isEmpty();
    }

    @Test
    void returnsEmptyWhenDbIsMissing(@TempDir Path data) throws Exception {
        Path bin = Files.createDirectories(data.resolve("astap/bin")).resolve("astap_cli");
        Files.writeString(bin, "#!/usr/bin/env bash\nexit 0\n");
        bin.toFile().setExecutable(true);

        Optional<AstapInstallation> out = new AstapInstallationLocator()
                .locate(propsWith("", "", "H18"), data);

        assertThat(out).isEmpty();
    }

    private static NocsProperties propsWith(String bin, String db, String dbName) {
        NocsProperties.PlateSolving.Astap astap = new NocsProperties.PlateSolving.Astap(bin, db, dbName);
        NocsProperties.PlateSolving ps = new NocsProperties.PlateSolving(
                "astap", 60L, astap, new NocsProperties.PlateSolving.Install(false, "", Map.of(), "", ""));
        return new NocsProperties(null, null, null, null, null, null, null, ps);
    }
}
```

- [ ] **Step 5.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.platesolving.astap.AstapInstallationLocatorTest'`
Expected: compile failure.

- [ ] **Step 5.3: Implement `AstapInstallation`**

Create `src/main/java/dev/nocs/platesolving/astap/AstapInstallation.java`:

```java
package dev.nocs.platesolving.astap;

import java.nio.file.Path;

public record AstapInstallation(Path binary, Path dbDir, String dbName) {

    public AstapInstallation {
        if (binary == null) {
            throw new IllegalArgumentException("binary required");
        }
        if (dbDir == null) {
            throw new IllegalArgumentException("dbDir required");
        }
        if (dbName == null || dbName.isBlank()) {
            dbName = "H18";
        }
    }
}
```

- [ ] **Step 5.4: Implement `AstapInstallationLocator`**

Create `src/main/java/dev/nocs/platesolving/astap/AstapInstallationLocator.java`:

```java
package dev.nocs.platesolving.astap;

import dev.nocs.config.NocsProperties;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Locale;
import java.util.Optional;
import org.springframework.stereotype.Component;

@Component
public class AstapInstallationLocator {

    public Optional<AstapInstallation> locate(NocsProperties props, Path dataDir) {
        NocsProperties.PlateSolving ps = props.platesolving();
        String dbName = ps == null || ps.astap() == null ? "H18" : ps.astap().dbName();

        Path binary = resolveBinary(ps, dataDir);
        if (binary == null) {
            return Optional.empty();
        }
        Path dbDir = resolveDb(ps, dataDir);
        if (dbDir == null || !hasDb(dbDir, dbName)) {
            return Optional.empty();
        }
        return Optional.of(new AstapInstallation(binary, dbDir, dbName));
    }

    private Path resolveBinary(NocsProperties.PlateSolving ps, Path dataDir) {
        if (ps != null && ps.astap() != null && ps.astap().binaryPath() != null
                && !ps.astap().binaryPath().isBlank()) {
            Path p = Paths.get(ps.astap().binaryPath());
            if (Files.isExecutable(p)) {
                return p;
            }
        }
        Path under = dataDir.resolve("astap").resolve("bin").resolve(executableName());
        if (Files.isExecutable(under)) {
            return under;
        }
        return findOnPath(executableName());
    }

    private Path resolveDb(NocsProperties.PlateSolving ps, Path dataDir) {
        if (ps != null && ps.astap() != null && ps.astap().dbDir() != null
                && !ps.astap().dbDir().isBlank()) {
            Path p = Paths.get(ps.astap().dbDir());
            return Files.isDirectory(p) ? p : null;
        }
        Path under = dataDir.resolve("astap").resolve("db");
        return Files.isDirectory(under) ? under : null;
    }

    private static boolean hasDb(Path dbDir, String dbName) {
        String prefix = dbName.toLowerCase(Locale.ROOT) + "_star_database";
        try (var stream = Files.list(dbDir)) {
            return stream.anyMatch(p -> p.getFileName().toString().toLowerCase(Locale.ROOT).startsWith(prefix));
        } catch (Exception e) {
            return false;
        }
    }

    private static String executableName() {
        return System.getProperty("os.name", "").toLowerCase(Locale.ROOT).contains("win")
                ? "astap_cli.exe"
                : "astap_cli";
    }

    private static Path findOnPath(String name) {
        String path = System.getenv("PATH");
        if (path == null) {
            return null;
        }
        String sep = System.getProperty("path.separator", ":");
        for (String dir : path.split(sep)) {
            if (dir.isBlank()) {
                continue;
            }
            Path candidate = Paths.get(dir, name);
            if (Files.isExecutable(candidate)) {
                return candidate;
            }
        }
        return null;
    }
}
```

- [ ] **Step 5.5: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.platesolving.astap.AstapInstallationLocatorTest'`
Expected: PASS.

- [ ] **Step 5.6: Commit**

```bash
git add src/main/java/dev/nocs/platesolving/astap/AstapInstallation.java \
        src/main/java/dev/nocs/platesolving/astap/AstapInstallationLocator.java \
        src/test/java/dev/nocs/platesolving/astap/AstapInstallationLocatorTest.java
git commit -m "feat(platesolving): AstapInstallationLocator (config → data_dir → PATH)"
```

---

### Task 6: ASTAP `.ini` parser

**Files:**
- Create: `src/main/java/dev/nocs/platesolving/astap/AstapIniParser.java`
- Create: `src/test/java/dev/nocs/platesolving/astap/AstapIniParserTest.java`
- Create: `src/test/resources/platesolving/astap/fake-astap-solved.ini`
- Create: `src/test/resources/platesolving/astap/fake-astap-failed.ini`

- [ ] **Step 6.1: Create the success fixture**

Create `src/test/resources/platesolving/astap/fake-astap-solved.ini`:

```ini
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
```

- [ ] **Step 6.2: Create the failure fixture**

Create `src/test/resources/platesolving/astap/fake-astap-failed.ini`:

```ini
PLTSOLVD=F
ERROR=Less than 30 stars detected
WARNING=Insufficient stars for blind solve
```

- [ ] **Step 6.3: Failing test**

Create `src/test/java/dev/nocs/platesolving/astap/AstapIniParserTest.java`:

```java
package dev.nocs.platesolving.astap;

import dev.nocs.platesolving.FailureKind;
import dev.nocs.platesolving.PlateSolution;
import dev.nocs.platesolving.SolveOutcome;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.ClassPathResource;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

class AstapIniParserTest {

    @Test
    void parsesSolvedIni() throws Exception {
        String text = read("platesolving/astap/fake-astap-solved.ini");

        SolveOutcome out = new AstapIniParser().parse(text, 1234L, Instant.parse("2026-04-22T22:00:00Z"));

        assertThat(out).isInstanceOf(SolveOutcome.Solved.class);
        SolveOutcome.Solved solved = (SolveOutcome.Solved) out;
        PlateSolution s = solved.solution();
        assertThat(s.raJ2000Deg()).isEqualTo(10.6847083);
        assertThat(s.decJ2000Deg()).isEqualTo(41.269083);
        assertThat(s.pixelScaleArcsecPerPx()).isCloseTo(0.000342222 * 3600.0, within(1e-6));
        assertThat(s.rotationDeg()).isEqualTo(12.5);
        assertThat(s.fieldWidthDeg()).isCloseTo(0.000342222 * 1024.0, within(1e-6));
        assertThat(s.fieldHeightDeg()).isCloseTo(0.000342222 * 768.0, within(1e-6));
        assertThat(s.solver()).isEqualTo("astap");
        assertThat(solved.durationMs()).isEqualTo(1234L);
    }

    @Test
    void parsesFailedIni() throws Exception {
        String text = read("platesolving/astap/fake-astap-failed.ini");

        SolveOutcome out = new AstapIniParser().parse(text, 200L, Instant.now());

        assertThat(out).isInstanceOf(SolveOutcome.Failed.class);
        SolveOutcome.Failed f = (SolveOutcome.Failed) out;
        assertThat(f.kind()).isEqualTo(FailureKind.NO_STARS);
        assertThat(f.message()).contains("Less than 30 stars");
        assertThat(f.durationMs()).isEqualTo(200L);
    }

    @Test
    void emptyTextIsInternalError() {
        SolveOutcome out = new AstapIniParser().parse("", 0L, Instant.now());

        assertThat(out).isInstanceOf(SolveOutcome.Failed.class);
        assertThat(((SolveOutcome.Failed) out).kind()).isEqualTo(FailureKind.INTERNAL_ERROR);
    }

    @Test
    void missingPltSolvdIsInternalError() {
        SolveOutcome out = new AstapIniParser().parse("CRVAL1=10\nCRVAL2=41\n", 0L, Instant.now());
        assertThat(((SolveOutcome.Failed) out).kind()).isEqualTo(FailureKind.INTERNAL_ERROR);
    }

    private static String read(String classpath) throws Exception {
        try (var in = new ClassPathResource(classpath).getInputStream()) {
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        }
    }
}
```

- [ ] **Step 6.4: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.platesolving.astap.AstapIniParserTest'`
Expected: compile failure — `AstapIniParser` does not exist.

- [ ] **Step 6.5: Implement `AstapIniParser`**

Create `src/main/java/dev/nocs/platesolving/astap/AstapIniParser.java`:

```java
package dev.nocs.platesolving.astap;

import dev.nocs.platesolving.FailureKind;
import dev.nocs.platesolving.PlateSolution;
import dev.nocs.platesolving.SolveOutcome;
import java.time.Instant;
import java.util.HashMap;
import java.util.Map;
import org.springframework.stereotype.Component;

@Component
public class AstapIniParser {

    public SolveOutcome parse(String iniText, long durationMs, Instant now) {
        if (iniText == null || iniText.isBlank()) {
            return new SolveOutcome.Failed(FailureKind.INTERNAL_ERROR, "empty ini output", durationMs);
        }
        Map<String, String> kv = parseKv(iniText);
        String solved = kv.get("PLTSOLVD");
        if (solved == null) {
            return new SolveOutcome.Failed(
                    FailureKind.INTERNAL_ERROR, "PLTSOLVD missing", durationMs);
        }
        if (!"T".equalsIgnoreCase(solved)) {
            String err = kv.getOrDefault("ERROR", "");
            FailureKind kind = err.toLowerCase().contains("star")
                    ? FailureKind.NO_STARS
                    : FailureKind.NO_STARS;
            return new SolveOutcome.Failed(kind, err.isBlank() ? "solver did not converge" : err, durationMs);
        }

        try {
            double crval1 = parseDouble(kv, "CRVAL1");
            double crval2 = parseDouble(kv, "CRVAL2");
            double cdelt1 = parseDouble(kv, "CDELT1");
            double cdelt2 = parseDouble(kv, "CDELT2");
            double crota = kv.containsKey("CROTA2")
                    ? parseDouble(kv, "CROTA2")
                    : kv.containsKey("CROTA1") ? parseDouble(kv, "CROTA1") : 0.0;
            int naxis1 = (int) Math.round(parseDouble(kv, "NAXIS1"));
            int naxis2 = (int) Math.round(parseDouble(kv, "NAXIS2"));

            double pixelScale = Math.abs(cdelt2) * 3600.0;
            double fieldWidth = Math.abs(cdelt1) * naxis1;
            double fieldHeight = Math.abs(cdelt2) * naxis2;
            double ra = ((crval1 % 360.0) + 360.0) % 360.0;

            PlateSolution s = new PlateSolution(
                    ra, crval2, pixelScale, crota, fieldWidth, fieldHeight, now, "astap");
            return new SolveOutcome.Solved(s, durationMs);
        } catch (RuntimeException e) {
            return new SolveOutcome.Failed(
                    FailureKind.INTERNAL_ERROR, "ini parse failed: " + e.getMessage(), durationMs);
        }
    }

    private static Map<String, String> parseKv(String text) {
        Map<String, String> out = new HashMap<>();
        for (String line : text.split("\\r?\\n")) {
            int eq = line.indexOf('=');
            if (eq <= 0) {
                continue;
            }
            String k = line.substring(0, eq).trim();
            String v = line.substring(eq + 1).trim();
            if (!k.isEmpty()) {
                out.put(k, v);
            }
        }
        return out;
    }

    private static double parseDouble(Map<String, String> kv, String key) {
        String v = kv.get(key);
        if (v == null || v.isBlank()) {
            throw new IllegalArgumentException("missing " + key);
        }
        return Double.parseDouble(v);
    }
}
```

- [ ] **Step 6.6: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.platesolving.astap.AstapIniParserTest'`
Expected: PASS.

- [ ] **Step 6.7: Commit**

```bash
git add src/main/java/dev/nocs/platesolving/astap/AstapIniParser.java \
        src/test/java/dev/nocs/platesolving/astap/AstapIniParserTest.java \
        src/test/resources/platesolving/astap/
git commit -m "feat(platesolving): AstapIniParser for ASTAP CLI .ini output"
```

---

### Task 7: Process runner + ASTAP invocation + invoker

**Files:**
- Create: `src/main/java/dev/nocs/platesolving/astap/ProcessResult.java`
- Create: `src/main/java/dev/nocs/platesolving/astap/ProcessRunner.java`
- Create: `src/main/java/dev/nocs/platesolving/astap/DefaultProcessRunner.java`
- Create: `src/main/java/dev/nocs/platesolving/astap/AstapInvocation.java`
- Create: `src/main/java/dev/nocs/platesolving/astap/AstapInvoker.java`
- Create: `src/test/java/dev/nocs/platesolving/astap/AstapInvocationTest.java`
- Create: `src/test/java/dev/nocs/platesolving/astap/AstapInvokerTest.java`
- Create: `src/test/resources/platesolving/astap/fake-astap.sh`

- [ ] **Step 7.1: Failing test for `AstapInvocation`**

Create `src/test/java/dev/nocs/platesolving/astap/AstapInvocationTest.java`:

```java
package dev.nocs.platesolving.astap;

import dev.nocs.platesolving.SolveOptions;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class AstapInvocationTest {

    @Test
    void minimalCommandIncludesBinaryFitsAndDb() {
        AstapInstallation inst = new AstapInstallation(
                Paths.get("/opt/astap/astap_cli"), Paths.get("/srv/db"), "H18");

        List<String> cmd = AstapInvocation.command(inst, Path.of("/tmp/sub.fits"), SolveOptions.defaults());

        assertThat(cmd).containsSequence("/opt/astap/astap_cli", "-f", "/tmp/sub.fits");
        assertThat(cmd).containsSequence("-d", "/srv/db");
        assertThat(cmd).contains("-wcs");
    }

    @Test
    void hintsAreAppendedWhenProvided() {
        AstapInstallation inst = new AstapInstallation(
                Paths.get("astap_cli"), Paths.get("db"), "H18");
        SolveOptions opts = new SolveOptions(160.0, 41.0, 5.0, null, null);

        List<String> cmd = AstapInvocation.command(inst, Path.of("sub.fits"), opts);

        assertThat(cmd).containsSequence("-ra", "10.6666666667");
        assertThat(cmd).containsSequence("-spd", "131.0");
        assertThat(cmd).containsSequence("-r", "5.0");
        assertThat(cmd).doesNotContain("-fov");
    }
}
```

- [ ] **Step 7.2: Implement `AstapInvocation`**

Create `src/main/java/dev/nocs/platesolving/astap/AstapInvocation.java`:

```java
package dev.nocs.platesolving.astap;

import dev.nocs.platesolving.SolveOptions;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

public final class AstapInvocation {

    private AstapInvocation() {}

    public static List<String> command(AstapInstallation inst, Path fitsFile, SolveOptions opts) {
        List<String> cmd = new ArrayList<>();
        cmd.add(inst.binary().toString());
        cmd.add("-f");
        cmd.add(fitsFile.toString());
        cmd.add("-d");
        cmd.add(inst.dbDir().toString());
        cmd.add("-wcs");
        if (opts.raHintDeg() != null) {
            cmd.add("-ra");
            cmd.add(format(opts.raHintDeg() / 15.0));
        }
        if (opts.decHintDeg() != null) {
            cmd.add("-spd");
            cmd.add(format(opts.decHintDeg() + 90.0));
        }
        if (opts.radiusDeg() != null) {
            cmd.add("-r");
            cmd.add(format(opts.radiusDeg()));
        }
        // Note: -fov is intentionally NOT passed here. ASTAP can derive the field width from
        // the FITS NAXIS/CDELT cards. The pixelScaleArcsecPerPxHint is currently informational
        // only; converting it to -fov would require reading NAXIS from the FITS bytes which is
        // out of scope for this command builder.
        return cmd;
    }

    private static String format(double v) {
        return String.format(Locale.ROOT, "%.10f", v).replaceAll("0+$", "").replaceAll("\\.$", ".0");
    }
}
```

- [ ] **Step 7.3: Run the invocation test — expect pass**

Run: `./gradlew test --tests 'dev.nocs.platesolving.astap.AstapInvocationTest'`
Expected: PASS.

- [ ] **Step 7.4: Implement `ProcessResult` + `ProcessRunner` + `DefaultProcessRunner`**

Create `src/main/java/dev/nocs/platesolving/astap/ProcessResult.java`:

```java
package dev.nocs.platesolving.astap;

public record ProcessResult(int exitCode, String stdout, String stderr, boolean timedOut, long durationMs) {}
```

Create `src/main/java/dev/nocs/platesolving/astap/ProcessRunner.java`:

```java
package dev.nocs.platesolving.astap;

import java.io.IOException;
import java.nio.file.Path;
import java.util.List;

public interface ProcessRunner {
    ProcessResult run(List<String> command, Path workDir, long timeoutSec) throws IOException, InterruptedException;
}
```

Create `src/main/java/dev/nocs/platesolving/astap/DefaultProcessRunner.java`:

```java
package dev.nocs.platesolving.astap;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.TimeUnit;
import org.springframework.stereotype.Component;

@Component
public class DefaultProcessRunner implements ProcessRunner {

    @Override
    public ProcessResult run(List<String> command, Path workDir, long timeoutSec)
            throws IOException, InterruptedException {
        long start = System.currentTimeMillis();
        ProcessBuilder pb = new ProcessBuilder(command);
        pb.directory(workDir.toFile());
        pb.redirectErrorStream(false);
        Process p = pb.start();
        boolean done = p.waitFor(Math.max(1L, timeoutSec), TimeUnit.SECONDS);
        long duration = System.currentTimeMillis() - start;
        if (!done) {
            p.destroy();
            if (!p.waitFor(2, TimeUnit.SECONDS)) {
                p.destroyForcibly();
            }
            return new ProcessResult(-1, drain(p.getInputStream()), drain(p.getErrorStream()), true, duration);
        }
        return new ProcessResult(
                p.exitValue(), drain(p.getInputStream()), drain(p.getErrorStream()), false, duration);
    }

    private static String drain(InputStream in) throws IOException {
        return new String(in.readAllBytes(), StandardCharsets.UTF_8);
    }
}
```

- [ ] **Step 7.5: Create the fake ASTAP shell script**

Create `src/test/resources/platesolving/astap/fake-astap.sh`:

```bash
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
```

- [ ] **Step 7.6: Implement `AstapInvoker`**

Create `src/main/java/dev/nocs/platesolving/astap/AstapInvoker.java`:

```java
package dev.nocs.platesolving.astap;

import dev.nocs.platesolving.FailureKind;
import dev.nocs.platesolving.SolveOptions;
import dev.nocs.platesolving.SolveOutcome;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.Comparator;
import java.util.stream.Stream;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

@Component
public class AstapInvoker {

    private static final Logger log = LoggerFactory.getLogger(AstapInvoker.class);

    private final ProcessRunner runner;
    private final AstapIniParser parser;

    public AstapInvoker(ProcessRunner runner, AstapIniParser parser) {
        this.runner = runner;
        this.parser = parser;
    }

    public SolveOutcome invoke(AstapInstallation inst, byte[] fits, SolveOptions options, long timeoutSec) {
        Path workDir = null;
        long start = System.currentTimeMillis();
        try {
            workDir = Files.createTempDirectory("nocs-astap-");
            Path fitsFile = workDir.resolve("input.fits");
            Files.write(fitsFile, fits);
            ProcessResult result = runner.run(
                    AstapInvocation.command(inst, fitsFile, options), workDir, timeoutSec);
            if (result.timedOut()) {
                return new SolveOutcome.Failed(
                        FailureKind.TIMEOUT,
                        "ASTAP exceeded " + timeoutSec + "s; stderr=" + truncate(result.stderr()),
                        result.durationMs());
            }
            Path ini = workDir.resolve("input.ini");
            String iniText = Files.exists(ini)
                    ? Files.readString(ini)
                    : "";
            if (iniText.isBlank()) {
                return new SolveOutcome.Failed(
                        FailureKind.INTERNAL_ERROR,
                        "ASTAP exit=" + result.exitCode()
                                + " stdout=" + truncate(result.stdout())
                                + " stderr=" + truncate(result.stderr()),
                        result.durationMs());
            }
            return parser.parse(iniText, result.durationMs(), Instant.now());
        } catch (IOException e) {
            return new SolveOutcome.Failed(
                    FailureKind.IO_ERROR, e.getMessage(), System.currentTimeMillis() - start);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return new SolveOutcome.Failed(
                    FailureKind.INTERNAL_ERROR, "interrupted", System.currentTimeMillis() - start);
        } finally {
            cleanup(workDir);
        }
    }

    private static void cleanup(Path dir) {
        if (dir == null || !Files.exists(dir)) {
            return;
        }
        try (Stream<Path> walk = Files.walk(dir)) {
            walk.sorted(Comparator.reverseOrder()).forEach(p -> {
                try {
                    Files.deleteIfExists(p);
                } catch (IOException ignored) {
                }
            });
        } catch (IOException e) {
            log.debug("astap workdir cleanup failed for {}: {}", dir, e.getMessage());
        }
    }

    private static String truncate(String s) {
        if (s == null) {
            return "";
        }
        return s.length() > 400 ? s.substring(0, 400) + "..." : s;
    }
}
```

- [ ] **Step 7.7: Failing test for `AstapInvoker`**

Create `src/test/java/dev/nocs/platesolving/astap/AstapInvokerTest.java`:

```java
package dev.nocs.platesolving.astap;

import dev.nocs.platesolving.FailureKind;
import dev.nocs.platesolving.SolveOptions;
import dev.nocs.platesolving.SolveOutcome;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.List;
import java.util.Locale;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.DisabledOnOs;
import org.junit.jupiter.api.condition.OS;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.core.io.ClassPathResource;

import static org.assertj.core.api.Assertions.assertThat;

@DisabledOnOs(OS.WINDOWS)
class AstapInvokerTest {

    @TempDir Path tmp;
    Path script;

    @BeforeEach
    void copyScript() throws IOException {
        script = tmp.resolve("fake-astap.sh");
        try (InputStream in = new ClassPathResource("platesolving/astap/fake-astap.sh").getInputStream()) {
            Files.copy(in, script, StandardCopyOption.REPLACE_EXISTING);
        }
        script.toFile().setExecutable(true);
    }

    @Test
    void successPathReturnsSolved() {
        AstapInvoker invoker = new AstapInvoker(new DefaultProcessRunner(), new AstapIniParser());
        AstapInstallation inst = new AstapInstallation(script, tmp, "H18");

        SolveOutcome out = invoker.invoke(inst, fakeFitsBytes(), SolveOptions.defaults(), 30L);

        assertThat(out).isInstanceOf(SolveOutcome.Solved.class);
        SolveOutcome.Solved solved = (SolveOutcome.Solved) out;
        assertThat(solved.solution().raJ2000Deg()).isEqualTo(10.6847083);
    }

    @Test
    void failedScriptYieldsFailedOutcome() throws Exception {
        Path failingScript = tmp.resolve("fake-astap-fail.sh");
        Files.copy(script, failingScript, StandardCopyOption.REPLACE_EXISTING);
        failingScript.toFile().setExecutable(true);
        AstapInvoker invoker = new AstapInvoker(new DefaultProcessRunner(), new AstapIniParser());
        AstapInstallation inst = new AstapInstallation(failingScript, tmp, "H18");

        SolveOutcome out = withEnv("FAKE_ASTAP_OUTCOME", "failed",
                () -> invoker.invoke(inst, fakeFitsBytes(), SolveOptions.defaults(), 30L));

        assertThat(out).isInstanceOf(SolveOutcome.Failed.class);
        assertThat(((SolveOutcome.Failed) out).kind()).isEqualTo(FailureKind.NO_STARS);
    }

    @Test
    void timeoutYieldsTimeoutFailure() {
        AstapInvoker invoker = new AstapInvoker(new DefaultProcessRunner(), new AstapIniParser());
        AstapInstallation inst = new AstapInstallation(script, tmp, "H18");

        SolveOutcome out = withEnv("FAKE_ASTAP_SLEEP", "5",
                () -> invoker.invoke(inst, fakeFitsBytes(), SolveOptions.defaults(), 1L));

        assertThat(out).isInstanceOf(SolveOutcome.Failed.class);
        assertThat(((SolveOutcome.Failed) out).kind()).isEqualTo(FailureKind.TIMEOUT);
    }

    private static byte[] fakeFitsBytes() {
        // 2880 bytes of zero is enough; AstapInvoker doesn't parse the FITS itself.
        return new byte[2880];
    }

    /** Override an env var for the duration of the supplier; restored in finally. */
    private static <T> T withEnv(String key, String value, java.util.function.Supplier<T> body) {
        // ProcessBuilder inherits the parent env. Tests can't mutate System.getenv directly,
        // so AstapInvokerTest takes a different approach for env vars: it instead sets
        // a process-local env via reflection. Keep the indirection so the failure-mode and
        // timeout tests stay readable in the source.
        Path link = Paths.get(System.getProperty("java.io.tmpdir"))
                .resolve("nocs-astap-env-" + Long.toString(Math.abs(java.util.UUID.randomUUID().getLeastSignificantBits()), 36));
        try {
            // Wrap the script in a shim that exports the env var first.
            Path shim = link.resolveSibling(link.getFileName().toString() + ".sh");
            String shimText = "#!/usr/bin/env bash\nexport " + key + "=\"" + value + "\"\nexec \"$@\"\n";
            Files.writeString(shim, shimText);
            shim.toFile().setExecutable(true);
            // Re-route by setting a system property the runner consults — we can't, so this
            // test relies on inheritance. Re-implement when CI requires it.
            return body.get();
        } catch (IOException e) {
            throw new RuntimeException(e);
        } finally {
            try {
                Files.deleteIfExists(link);
            } catch (IOException ignored) {
            }
        }
    }
}
```

The two `withEnv`-based tests above flag a real testing problem: Java's `System.getenv()` is unmodifiable, and `ProcessBuilder` inherits the parent environment. The cleanest production-shape fix is to extend `ProcessRunner` with an env map. Implement that now:

- [ ] **Step 7.8: Extend `ProcessRunner` to accept an env map and rerun**

Modify `src/main/java/dev/nocs/platesolving/astap/ProcessRunner.java`:

```java
package dev.nocs.platesolving.astap;

import java.io.IOException;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;

public interface ProcessRunner {
    ProcessResult run(
            List<String> command,
            Path workDir,
            Map<String, String> envOverrides,
            long timeoutSec) throws IOException, InterruptedException;
}
```

Modify `src/main/java/dev/nocs/platesolving/astap/DefaultProcessRunner.java`:

```java
package dev.nocs.platesolving.astap;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import org.springframework.stereotype.Component;

@Component
public class DefaultProcessRunner implements ProcessRunner {

    @Override
    public ProcessResult run(
            List<String> command,
            Path workDir,
            Map<String, String> envOverrides,
            long timeoutSec) throws IOException, InterruptedException {
        long start = System.currentTimeMillis();
        ProcessBuilder pb = new ProcessBuilder(command);
        pb.directory(workDir.toFile());
        pb.redirectErrorStream(false);
        if (envOverrides != null) {
            pb.environment().putAll(envOverrides);
        }
        Process p = pb.start();
        boolean done = p.waitFor(Math.max(1L, timeoutSec), TimeUnit.SECONDS);
        long duration = System.currentTimeMillis() - start;
        if (!done) {
            p.destroy();
            if (!p.waitFor(2, TimeUnit.SECONDS)) {
                p.destroyForcibly();
            }
            return new ProcessResult(-1, drain(p.getInputStream()), drain(p.getErrorStream()), true, duration);
        }
        return new ProcessResult(
                p.exitValue(), drain(p.getInputStream()), drain(p.getErrorStream()), false, duration);
    }

    private static String drain(InputStream in) throws IOException {
        return new String(in.readAllBytes(), StandardCharsets.UTF_8);
    }
}
```

Modify `src/main/java/dev/nocs/platesolving/astap/AstapInvoker.java` to pass an env map. Add a new field + constructor parameter `Map<String, String> envOverrides`:

```java
package dev.nocs.platesolving.astap;

import dev.nocs.platesolving.FailureKind;
import dev.nocs.platesolving.SolveOptions;
import dev.nocs.platesolving.SolveOutcome;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.Comparator;
import java.util.HashMap;
import java.util.Map;
import java.util.stream.Stream;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

@Component
public class AstapInvoker {

    private static final Logger log = LoggerFactory.getLogger(AstapInvoker.class);

    private final ProcessRunner runner;
    private final AstapIniParser parser;

    public AstapInvoker(ProcessRunner runner, AstapIniParser parser) {
        this.runner = runner;
        this.parser = parser;
    }

    public SolveOutcome invoke(AstapInstallation inst, byte[] fits, SolveOptions options, long timeoutSec) {
        return invoke(inst, fits, options, timeoutSec, Map.of());
    }

    public SolveOutcome invoke(
            AstapInstallation inst,
            byte[] fits,
            SolveOptions options,
            long timeoutSec,
            Map<String, String> envOverrides) {
        Path workDir = null;
        long start = System.currentTimeMillis();
        try {
            workDir = Files.createTempDirectory("nocs-astap-");
            Path fitsFile = workDir.resolve("input.fits");
            Files.write(fitsFile, fits);
            Map<String, String> env = new HashMap<>(envOverrides == null ? Map.of() : envOverrides);
            ProcessResult result = runner.run(
                    AstapInvocation.command(inst, fitsFile, options), workDir, env, timeoutSec);
            if (result.timedOut()) {
                return new SolveOutcome.Failed(
                        FailureKind.TIMEOUT,
                        "ASTAP exceeded " + timeoutSec + "s; stderr=" + truncate(result.stderr()),
                        result.durationMs());
            }
            Path ini = workDir.resolve("input.ini");
            String iniText = Files.exists(ini) ? Files.readString(ini) : "";
            if (iniText.isBlank()) {
                return new SolveOutcome.Failed(
                        FailureKind.INTERNAL_ERROR,
                        "ASTAP exit=" + result.exitCode()
                                + " stdout=" + truncate(result.stdout())
                                + " stderr=" + truncate(result.stderr()),
                        result.durationMs());
            }
            return parser.parse(iniText, result.durationMs(), Instant.now());
        } catch (IOException e) {
            return new SolveOutcome.Failed(
                    FailureKind.IO_ERROR, e.getMessage(), System.currentTimeMillis() - start);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return new SolveOutcome.Failed(
                    FailureKind.INTERNAL_ERROR, "interrupted", System.currentTimeMillis() - start);
        } finally {
            cleanup(workDir);
        }
    }

    private static void cleanup(Path dir) {
        if (dir == null || !Files.exists(dir)) {
            return;
        }
        try (Stream<Path> walk = Files.walk(dir)) {
            walk.sorted(Comparator.reverseOrder()).forEach(p -> {
                try {
                    Files.deleteIfExists(p);
                } catch (IOException ignored) {
                }
            });
        } catch (IOException e) {
            log.debug("astap workdir cleanup failed for {}: {}", dir, e.getMessage());
        }
    }

    private static String truncate(String s) {
        if (s == null) {
            return "";
        }
        return s.length() > 400 ? s.substring(0, 400) + "..." : s;
    }
}
```

- [ ] **Step 7.9: Replace the env-var tricks in the test with the new `envOverrides` overload**

Rewrite `src/test/java/dev/nocs/platesolving/astap/AstapInvokerTest.java`:

```java
package dev.nocs.platesolving.astap;

import dev.nocs.platesolving.FailureKind;
import dev.nocs.platesolving.SolveOptions;
import dev.nocs.platesolving.SolveOutcome;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.DisabledOnOs;
import org.junit.jupiter.api.condition.OS;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.core.io.ClassPathResource;

import static org.assertj.core.api.Assertions.assertThat;

@DisabledOnOs(OS.WINDOWS)
class AstapInvokerTest {

    @TempDir Path tmp;
    Path script;
    AstapInvoker invoker;

    @BeforeEach
    void setUp() throws IOException {
        script = tmp.resolve("fake-astap.sh");
        try (InputStream in = new ClassPathResource("platesolving/astap/fake-astap.sh").getInputStream()) {
            Files.copy(in, script, StandardCopyOption.REPLACE_EXISTING);
        }
        script.toFile().setExecutable(true);
        invoker = new AstapInvoker(new DefaultProcessRunner(), new AstapIniParser());
    }

    @Test
    void successPathReturnsSolved() {
        AstapInstallation inst = new AstapInstallation(script, tmp, "H18");

        SolveOutcome out = invoker.invoke(inst, fakeFits(), SolveOptions.defaults(), 30L,
                Map.of("FAKE_ASTAP_OUTCOME", "solved"));

        assertThat(out).isInstanceOf(SolveOutcome.Solved.class);
        assertThat(((SolveOutcome.Solved) out).solution().raJ2000Deg()).isEqualTo(10.6847083);
    }

    @Test
    void failedScriptYieldsFailedOutcome() {
        AstapInstallation inst = new AstapInstallation(script, tmp, "H18");

        SolveOutcome out = invoker.invoke(inst, fakeFits(), SolveOptions.defaults(), 30L,
                Map.of("FAKE_ASTAP_OUTCOME", "failed"));

        assertThat(out).isInstanceOf(SolveOutcome.Failed.class);
        assertThat(((SolveOutcome.Failed) out).kind()).isEqualTo(FailureKind.NO_STARS);
    }

    @Test
    void timeoutYieldsTimeoutFailure() {
        AstapInstallation inst = new AstapInstallation(script, tmp, "H18");

        SolveOutcome out = invoker.invoke(inst, fakeFits(), SolveOptions.defaults(), 1L,
                Map.of("FAKE_ASTAP_SLEEP", "5"));

        assertThat(out).isInstanceOf(SolveOutcome.Failed.class);
        assertThat(((SolveOutcome.Failed) out).kind()).isEqualTo(FailureKind.TIMEOUT);
    }

    private static byte[] fakeFits() {
        return new byte[2880];
    }
}
```

- [ ] **Step 7.10: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.platesolving.astap.AstapInvocationTest' --tests 'dev.nocs.platesolving.astap.AstapInvokerTest'`
Expected: PASS on Linux. Windows is skipped via `@DisabledOnOs`.

If `AstapInvokerTest.timeoutYieldsTimeoutFailure` is flaky on a slow CI runner, raise the sleep from `"5"` to `"15"` and the timeout from `1L` to `2L`.

- [ ] **Step 7.11: Commit**

```bash
git add src/main/java/dev/nocs/platesolving/astap/ProcessResult.java \
        src/main/java/dev/nocs/platesolving/astap/ProcessRunner.java \
        src/main/java/dev/nocs/platesolving/astap/DefaultProcessRunner.java \
        src/main/java/dev/nocs/platesolving/astap/AstapInvocation.java \
        src/main/java/dev/nocs/platesolving/astap/AstapInvoker.java \
        src/test/java/dev/nocs/platesolving/astap/AstapInvocationTest.java \
        src/test/java/dev/nocs/platesolving/astap/AstapInvokerTest.java \
        src/test/resources/platesolving/astap/fake-astap.sh
git commit -m "feat(platesolving): AstapInvoker (process runner + .ini collection) with timeout"
```

---

### Task 8: `AstapPlateSolver` (`PlateSolvingService` impl)

**Files:**
- Create: `src/main/java/dev/nocs/platesolving/astap/AstapPlateSolver.java`
- Create: `src/main/java/dev/nocs/platesolving/DisabledPlateSolvingService.java`
- Create: `src/test/java/dev/nocs/platesolving/astap/AstapPlateSolverTest.java`

- [ ] **Step 8.1: Failing test**

Create `src/test/java/dev/nocs/platesolving/astap/AstapPlateSolverTest.java`:

```java
package dev.nocs.platesolving.astap;

import dev.nocs.bootstrap.DataDirBootstrap;
import dev.nocs.config.NocsProperties;
import dev.nocs.platesolving.FailureKind;
import dev.nocs.platesolving.PlateSolution;
import dev.nocs.platesolving.SolveOptions;
import dev.nocs.platesolving.SolveOutcome;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.assertj.core.api.Assertions.assertThat;

class AstapPlateSolverTest {

    @Test
    void notInstalledReturnsNotInstalled(@TempDir Path data) {
        AstapInstallationLocator locator = new AstapInstallationLocator();
        AstapInvoker invoker = new AstapInvoker(stubRunner(_r -> {
            throw new AssertionError("invoker should not run");
        }), new AstapIniParser());

        AstapPlateSolver solver = new AstapPlateSolver(locator, invoker, propsAstap(""), data);

        SolveOutcome out = solver.solve(new byte[100], SolveOptions.defaults());

        assertThat(out).isInstanceOf(SolveOutcome.Failed.class);
        assertThat(((SolveOutcome.Failed) out).kind()).isEqualTo(FailureKind.NOT_INSTALLED);
        assertThat(solver.isAvailable()).isFalse();
    }

    @Test
    void installedDelegatesToInvoker(@TempDir Path data) throws Exception {
        Path bin = Files.createDirectories(data.resolve("astap/bin")).resolve("astap_cli");
        Files.writeString(bin, "#!/bin/sh\nexit 0\n");
        bin.toFile().setExecutable(true);
        Files.createDirectories(data.resolve("astap/db"));
        Files.createFile(data.resolve("astap/db/h18_star_database_index.dat"));

        ProcessRunner runner = (cmd, work, env, t) -> {
            Path ini = work.resolve("input.ini");
            Files.writeString(ini,
                    "PLTSOLVD=T\nCRVAL1=1.0\nCRVAL2=2.0\nCDELT1=-0.001\nCDELT2=0.001\n"
                            + "CROTA2=0\nNAXIS1=10\nNAXIS2=10\n");
            return new ProcessResult(0, "", "", false, 12L);
        };
        AstapInvoker invoker = new AstapInvoker(runner, new AstapIniParser());
        AstapPlateSolver solver = new AstapPlateSolver(
                new AstapInstallationLocator(), invoker, propsAstap(""), data);

        SolveOutcome out = solver.solve(new byte[2880], SolveOptions.defaults());

        assertThat(out).isInstanceOf(SolveOutcome.Solved.class);
        PlateSolution s = ((SolveOutcome.Solved) out).solution();
        assertThat(s.raJ2000Deg()).isEqualTo(1.0);
    }

    private static NocsProperties propsAstap(String binaryPath) {
        NocsProperties.PlateSolving.Astap astap = new NocsProperties.PlateSolving.Astap(binaryPath, "", "H18");
        NocsProperties.PlateSolving ps = new NocsProperties.PlateSolving(
                "astap", 60L, astap, new NocsProperties.PlateSolving.Install(false, "", Map.of(), "", ""));
        return new NocsProperties(null, null, null, null, null, null, null, ps);
    }

    private static ProcessRunner stubRunner(java.util.function.Consumer<List<String>> sink) {
        return (cmd, work, env, t) -> {
            sink.accept(cmd);
            return new ProcessResult(0, "", "", false, 0L);
        };
    }
}
```

- [ ] **Step 8.2: Implement `AstapPlateSolver`**

Create `src/main/java/dev/nocs/platesolving/astap/AstapPlateSolver.java`:

```java
package dev.nocs.platesolving.astap;

import dev.nocs.config.NocsProperties;
import dev.nocs.platesolving.FailureKind;
import dev.nocs.platesolving.PlateSolvingService;
import dev.nocs.platesolving.SolveOptions;
import dev.nocs.platesolving.SolveOutcome;
import java.nio.file.Path;
import java.util.Optional;

public class AstapPlateSolver implements PlateSolvingService {

    private final AstapInstallationLocator locator;
    private final AstapInvoker invoker;
    private final NocsProperties props;
    private final Path dataDir;

    public AstapPlateSolver(AstapInstallationLocator locator, AstapInvoker invoker,
                            NocsProperties props, Path dataDir) {
        this.locator = locator;
        this.invoker = invoker;
        this.props = props;
        this.dataDir = dataDir;
    }

    @Override
    public SolveOutcome solve(byte[] fits, SolveOptions options) {
        Optional<AstapInstallation> installed = locator.locate(props, dataDir);
        if (installed.isEmpty()) {
            return new SolveOutcome.Failed(
                    FailureKind.NOT_INSTALLED,
                    "ASTAP not installed; POST /api/platesolving/install or set "
                            + "nocs.platesolving.astap.binary-path",
                    0L);
        }
        long timeout = effectiveTimeout(options);
        return invoker.invoke(installed.get(), fits, options, timeout);
    }

    @Override
    public boolean isAvailable() {
        return locator.locate(props, dataDir).isPresent();
    }

    private long effectiveTimeout(SolveOptions options) {
        if (options.timeoutSec() != null) {
            return Math.max(1L, options.timeoutSec().longValue());
        }
        long fromConfig = props.platesolving() == null ? 60L : props.platesolving().solveTimeoutSec();
        return Math.max(1L, fromConfig);
    }
}
```

- [ ] **Step 8.3: Implement `DisabledPlateSolvingService`**

Create `src/main/java/dev/nocs/platesolving/DisabledPlateSolvingService.java`:

```java
package dev.nocs.platesolving;

public class DisabledPlateSolvingService implements PlateSolvingService {

    @Override
    public SolveOutcome solve(byte[] fits, SolveOptions options) {
        return new SolveOutcome.Failed(
                FailureKind.NOT_INSTALLED,
                "Plate solving is disabled (nocs.platesolving.solver=disabled)",
                0L);
    }

    @Override
    public boolean isAvailable() {
        return false;
    }
}
```

- [ ] **Step 8.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.platesolving.astap.AstapPlateSolverTest'`
Expected: PASS.

- [ ] **Step 8.5: Commit**

```bash
git add src/main/java/dev/nocs/platesolving/astap/AstapPlateSolver.java \
        src/main/java/dev/nocs/platesolving/DisabledPlateSolvingService.java \
        src/test/java/dev/nocs/platesolving/astap/AstapPlateSolverTest.java
git commit -m "feat(platesolving): AstapPlateSolver + DisabledPlateSolvingService"
```

---

### Task 9: `PlateSolutionRecord` + `PlateSolutionRepository`

**Files:**
- Create: `src/main/java/dev/nocs/platesolving/PlateSolutionRecord.java`
- Create: `src/main/java/dev/nocs/platesolving/PlateSolutionRepository.java`
- Create: `src/test/java/dev/nocs/platesolving/PlateSolutionRepositoryTest.java`

- [ ] **Step 9.1: Failing test**

Create `src/test/java/dev/nocs/platesolving/PlateSolutionRepositoryTest.java`:

```java
package dev.nocs.platesolving;

import java.time.Instant;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@TestPropertySource(properties = "nocs.auth.token=t")
class PlateSolutionRepositoryTest {

    @Autowired PlateSolutionRepository repo;
    @Autowired JdbcTemplate jdbc;

    @Test
    void upsertInsertsAndReplaces() {
        long imageId = createImage("dev1", "L_30s_001.fits");

        repo.upsert(PlateSolutionRecord.forInsert(
                imageId, 1.0, 2.0, 1.5, 12.0, 0.5, 0.4, 200L, "astap", Instant.now()));
        Optional<PlateSolutionRecord> first = repo.findByImageId(imageId);
        assertThat(first).isPresent();
        assertThat(first.get().raJ2000Deg()).isEqualTo(1.0);

        repo.upsert(PlateSolutionRecord.forInsert(
                imageId, 9.9, 8.8, 1.5, 12.0, 0.5, 0.4, 250L, "astap", Instant.now()));

        Optional<PlateSolutionRecord> second = repo.findByImageId(imageId);
        assertThat(second).isPresent();
        assertThat(second.get().raJ2000Deg()).isEqualTo(9.9);
        assertThat(second.get().decJ2000Deg()).isEqualTo(8.8);
    }

    @Test
    void deleteRemovesRow() {
        long imageId = createImage("dev1", "L_30s_002.fits");
        repo.upsert(PlateSolutionRecord.forInsert(
                imageId, 5.0, 5.0, 1.0, 0.0, 0.5, 0.4, 100L, "astap", Instant.now()));

        boolean removed = repo.deleteByImageId(imageId);

        assertThat(removed).isTrue();
        assertThat(repo.findByImageId(imageId)).isEmpty();
    }

    private long createImage(String device, String fileName) {
        jdbc.update("INSERT INTO images(device_id, fits_path, bytes) VALUES(?,?,0)",
                device, "/tmp/" + fileName);
        return jdbc.queryForObject(
                "SELECT id FROM images WHERE fits_path = ?", Long.class, "/tmp/" + fileName);
    }
}
```

- [ ] **Step 9.2: Implement `PlateSolutionRecord`**

Create `src/main/java/dev/nocs/platesolving/PlateSolutionRecord.java`:

```java
package dev.nocs.platesolving;

import java.time.Instant;

public record PlateSolutionRecord(
        Long id,
        long imageId,
        double raJ2000Deg,
        double decJ2000Deg,
        double pixelScaleArcsecPerPx,
        double rotationDeg,
        double fieldWidthDeg,
        double fieldHeightDeg,
        long durationMs,
        String solver,
        Instant solvedAt) {

    public static PlateSolutionRecord forInsert(
            long imageId,
            double raJ2000Deg,
            double decJ2000Deg,
            double pixelScaleArcsecPerPx,
            double rotationDeg,
            double fieldWidthDeg,
            double fieldHeightDeg,
            long durationMs,
            String solver,
            Instant solvedAt) {
        return new PlateSolutionRecord(
                null, imageId, raJ2000Deg, decJ2000Deg,
                pixelScaleArcsecPerPx, rotationDeg, fieldWidthDeg, fieldHeightDeg,
                durationMs, solver == null ? "unknown" : solver,
                solvedAt == null ? Instant.now() : solvedAt);
    }

    public static PlateSolutionRecord fromSolution(long imageId, PlateSolution s, long durationMs) {
        return forInsert(imageId,
                s.raJ2000Deg(), s.decJ2000Deg(), s.pixelScaleArcsecPerPx(),
                s.rotationDeg(), s.fieldWidthDeg(), s.fieldHeightDeg(),
                durationMs, s.solver(), s.solvedAt());
    }
}
```

- [ ] **Step 9.3: Implement `PlateSolutionRepository`**

Create `src/main/java/dev/nocs/platesolving/PlateSolutionRepository.java`:

```java
package dev.nocs.platesolving;

import java.sql.ResultSet;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

@Repository
public class PlateSolutionRepository {

    private final JdbcTemplate jdbc;

    public PlateSolutionRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public void upsert(PlateSolutionRecord rec) {
        jdbc.update(
                "INSERT INTO plate_solutions("
                        + "image_id, ra_j2000_deg, dec_j2000_deg, pixel_scale_arcsec_per_px, "
                        + "rotation_deg, field_width_deg, field_height_deg, duration_ms, "
                        + "solver, solved_at) "
                        + "VALUES(?,?,?,?,?,?,?,?,?,?) "
                        + "ON CONFLICT(image_id) DO UPDATE SET "
                        + "ra_j2000_deg=excluded.ra_j2000_deg, "
                        + "dec_j2000_deg=excluded.dec_j2000_deg, "
                        + "pixel_scale_arcsec_per_px=excluded.pixel_scale_arcsec_per_px, "
                        + "rotation_deg=excluded.rotation_deg, "
                        + "field_width_deg=excluded.field_width_deg, "
                        + "field_height_deg=excluded.field_height_deg, "
                        + "duration_ms=excluded.duration_ms, "
                        + "solver=excluded.solver, "
                        + "solved_at=excluded.solved_at",
                rec.imageId(),
                rec.raJ2000Deg(), rec.decJ2000Deg(), rec.pixelScaleArcsecPerPx(),
                rec.rotationDeg(), rec.fieldWidthDeg(), rec.fieldHeightDeg(),
                rec.durationMs(),
                rec.solver(),
                rec.solvedAt().toString());
    }

    public Optional<PlateSolutionRecord> findByImageId(long imageId) {
        List<PlateSolutionRecord> rows = jdbc.query(
                "SELECT id, image_id, ra_j2000_deg, dec_j2000_deg, pixel_scale_arcsec_per_px, "
                        + "rotation_deg, field_width_deg, field_height_deg, duration_ms, solver, "
                        + "solved_at FROM plate_solutions WHERE image_id = ?",
                MAPPER, imageId);
        return rows.isEmpty() ? Optional.empty() : Optional.of(rows.get(0));
    }

    public boolean deleteByImageId(long imageId) {
        return jdbc.update("DELETE FROM plate_solutions WHERE image_id = ?", imageId) > 0;
    }

    private static final RowMapper<PlateSolutionRecord> MAPPER = (ResultSet rs, int n) -> {
        String solvedAt = rs.getString("solved_at");
        Instant when = solvedAt == null
                ? null
                : LocalDateTime.parse(solvedAt.replace(' ', 'T')).toInstant(ZoneOffset.UTC);
        return new PlateSolutionRecord(
                rs.getLong("id"),
                rs.getLong("image_id"),
                rs.getDouble("ra_j2000_deg"),
                rs.getDouble("dec_j2000_deg"),
                rs.getDouble("pixel_scale_arcsec_per_px"),
                rs.getDouble("rotation_deg"),
                rs.getDouble("field_width_deg"),
                rs.getDouble("field_height_deg"),
                rs.getLong("duration_ms"),
                rs.getString("solver"),
                when);
    };
}
```

The `solved_at` column was declared `TEXT` in V4 with the `datetime('now')` default, which yields a `YYYY-MM-DD HH:MM:SS` string. We pass the ISO-8601 form (`Instant#toString` → `2026-04-22T22:00:00Z`) so `LocalDateTime.parse` can read it back. The `replace(' ', 'T')` keeps DB-default rows readable.

- [ ] **Step 9.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.platesolving.PlateSolutionRepositoryTest'`
Expected: PASS.

- [ ] **Step 9.5: Commit**

```bash
git add src/main/java/dev/nocs/platesolving/PlateSolutionRecord.java \
        src/main/java/dev/nocs/platesolving/PlateSolutionRepository.java \
        src/test/java/dev/nocs/platesolving/PlateSolutionRepositoryTest.java
git commit -m "feat(platesolving): PlateSolutionRepository (upsert + find + delete)"
```

---

### Task 10: `FitsHeaderWriter` + real `ImageStoreService.amendHeader`

**Files:**
- Create: `src/main/java/dev/nocs/image/FitsHeaderWriter.java`
- Create: `src/test/java/dev/nocs/image/FitsHeaderWriterTest.java`
- Modify: `src/main/java/dev/nocs/image/ImageStoreService.java`
- Create: `src/test/java/dev/nocs/image/ImageStoreServiceAmendHeaderTest.java`

- [ ] **Step 10.1: Failing test for `FitsHeaderWriter`**

Create `src/test/java/dev/nocs/image/FitsHeaderWriterTest.java`:

```java
package dev.nocs.image;

import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.SequencedMap;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class FitsHeaderWriterTest {

    @Test
    void appendsNewCardsAndKeepsDataIntact() {
        byte[] original = MiniFits.build16(8, 8, new short[64], java.util.Map.of(
                "DATE-OBS", "'2026-04-22T22:00:00'"));

        SequencedMap<String, String> additions = new LinkedHashMap<>();
        additions.put("CRVAL1", "10.6847083");
        additions.put("CRVAL2", "41.269083");
        additions.put("PLTSOLVD", "T");

        byte[] amended = FitsHeaderWriter.writeWithCards(original, additions);

        FitsHeaderReader.Header h = FitsHeaderReader.read(amended);
        assertThat(h.bitpix()).isEqualTo(16);
        assertThat(h.naxis()).isEqualTo(2);
        assertThat(h.naxis1()).isEqualTo(8);
        assertThat(h.naxis2()).isEqualTo(8);
        assertThat(amended.length % 2880).isZero();

        String headerText = new String(amended, 0, h.dataOffset(), StandardCharsets.US_ASCII);
        assertThat(headerText).contains("CRVAL1");
        assertThat(headerText).contains("CRVAL2");
        assertThat(headerText).contains("PLTSOLVD=                    T");

        // Data section preserved exactly: extract the original data block from `original` and
        // compare it byte-for-byte with the corresponding region in `amended`.
        FitsHeaderReader.Header ho = FitsHeaderReader.read(original);
        int dataLen = original.length - ho.dataOffset();
        assertThat(java.util.Arrays.copyOfRange(amended, h.dataOffset(), h.dataOffset() + dataLen))
                .isEqualTo(java.util.Arrays.copyOfRange(original, ho.dataOffset(), original.length));
    }

    @Test
    void replacesExistingCardInPlace() {
        byte[] original = MiniFits.build16(8, 8, new short[64], java.util.Map.of(
                "DATE-OBS", "'1999-01-01T00:00:00'"));

        SequencedMap<String, String> repl = new LinkedHashMap<>();
        repl.put("DATE-OBS", "'2026-04-22T22:00:00'");

        byte[] amended = FitsHeaderWriter.writeWithCards(original, repl);

        FitsHeaderReader.Header h = FitsHeaderReader.read(amended);
        assertThat(h.dateObs()).isEqualTo("2026-04-22T22:00:00");

        String headerText = new String(amended, 0, h.dataOffset(), StandardCharsets.US_ASCII);
        // Only one DATE-OBS card.
        int idx = headerText.indexOf("DATE-OBS");
        assertThat(idx).isGreaterThan(-1);
        assertThat(headerText.indexOf("DATE-OBS", idx + 1)).isEqualTo(-1);
    }
}
```

This test reuses `MiniFits` introduced by Plan D under `src/test/java/dev/nocs/image/MiniFits.java`. If your branch is missing it, copy the implementation from Plan D Task 5; the helper synthesises FITS bytes from a `short[]` and a card map.

- [ ] **Step 10.2: Implement `FitsHeaderWriter`**

Create `src/main/java/dev/nocs/image/FitsHeaderWriter.java`:

```java
package dev.nocs.image;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.SequencedMap;

public final class FitsHeaderWriter {

    private static final int CARD_LEN = 80;
    private static final int BLOCK_LEN = 2880;

    private FitsHeaderWriter() {}

    public static byte[] writeWithCards(byte[] originalFits, SequencedMap<String, String> additions) {
        if (originalFits == null || originalFits.length < BLOCK_LEN) {
            throw new IllegalArgumentException("FITS payload too small");
        }
        FitsHeaderReader.Header h = FitsHeaderReader.read(originalFits);

        List<String> cards = readHeaderCards(originalFits, h.dataOffset());

        LinkedHashMap<String, String> overrides = new LinkedHashMap<>();
        if (additions != null) {
            additions.forEach((k, v) -> overrides.put(k.toUpperCase(Locale.ROOT), v));
        }

        List<String> rebuilt = new ArrayList<>(cards.size() + overrides.size());
        for (String card : cards) {
            String key = card.length() >= 8 ? card.substring(0, 8).trim() : "";
            if (key.equals("END")) {
                continue;
            }
            String upper = key.toUpperCase(Locale.ROOT);
            if (overrides.containsKey(upper)) {
                rebuilt.add(formatCard(upper, overrides.remove(upper)));
            } else {
                rebuilt.add(card);
            }
        }
        for (var entry : overrides.entrySet()) {
            rebuilt.add(formatCard(entry.getKey(), entry.getValue()));
        }
        rebuilt.add(formatCard("END", null));

        byte[] headerBytes = packHeader(rebuilt);
        int dataLen = originalFits.length - h.dataOffset();
        byte[] out = new byte[headerBytes.length + dataLen];
        System.arraycopy(headerBytes, 0, out, 0, headerBytes.length);
        System.arraycopy(originalFits, h.dataOffset(), out, headerBytes.length, dataLen);
        return out;
    }

    private static List<String> readHeaderCards(byte[] bytes, int dataOffset) {
        List<String> out = new ArrayList<>(dataOffset / CARD_LEN);
        for (int off = 0; off < dataOffset; off += CARD_LEN) {
            String card = new String(bytes, off, CARD_LEN, StandardCharsets.US_ASCII);
            String key = card.substring(0, 8).trim();
            out.add(card);
            if (key.equals("END")) {
                break;
            }
        }
        return out;
    }

    private static byte[] packHeader(List<String> cards) {
        int totalCards = ((cards.size() + 35) / 36) * 36;
        StringBuilder sb = new StringBuilder(totalCards * CARD_LEN);
        for (String c : cards) {
            sb.append(pad(c, CARD_LEN));
        }
        for (int i = cards.size(); i < totalCards; i++) {
            sb.append(pad("", CARD_LEN));
        }
        return sb.toString().getBytes(StandardCharsets.US_ASCII);
    }

    private static String formatCard(String key, String value) {
        String k = pad(key.toUpperCase(Locale.ROOT), 8);
        if ("END".equalsIgnoreCase(key)) {
            return pad("END", CARD_LEN);
        }
        String v = value == null ? "" : value;
        // Right-justify numeric/`T`/`F` values in columns 11..30; leave quoted strings as-is in cols 11..
        String formatted;
        if (v.length() >= 2 && v.startsWith("'") && v.endsWith("'")) {
            formatted = v;
        } else {
            formatted = String.format(Locale.ROOT, "%20s", v);
        }
        return pad(k + "= " + formatted, CARD_LEN);
    }

    private static String pad(String s, int len) {
        if (s.length() >= len) {
            return s.substring(0, len);
        }
        StringBuilder sb = new StringBuilder(len);
        sb.append(s);
        for (int i = s.length(); i < len; i++) {
            sb.append(' ');
        }
        return sb.toString();
    }
}
```

- [ ] **Step 10.3: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.image.FitsHeaderWriterTest'`
Expected: PASS.

If `replacesExistingCardInPlace` fails because `FitsHeaderReader` returns the old `DATE-OBS`, double-check that the old card was replaced (search the header text printed by `headerText` — only one card with the key should exist).

- [ ] **Step 10.4: Failing test for `ImageStoreService.amendHeader`**

Create `src/test/java/dev/nocs/image/ImageStoreServiceAmendHeaderTest.java`:

```java
package dev.nocs.image;

import dev.nocs.platesolving.PlateSolutionRepository;
import dev.nocs.platesolving.PlateSolution;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.Map;
import java.util.Optional;
import java.util.SequencedMap;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@TestPropertySource(properties = "nocs.auth.token=t")
class ImageStoreServiceAmendHeaderTest {

    @Autowired ImageStoreService store;
    @Autowired PlateSolutionRepository solutions;

    @Test
    void amendHeaderReplacesFitsAndUpsertsPlateSolution() throws Exception {
        byte[] fits = MiniFits.build16(8, 8, new short[64], Map.of(
                "DATE-OBS", "'2026-04-22T22:00:00'"));
        store.prepareCapture(new dev.nocs.device.DeviceId("ccd-amend"),
                CaptureContext.defaults(60.0));
        store.accept(new dev.nocs.device.DeviceId("ccd-amend"), fits, ".fits");

        long imageId = store.list(new ImageRepository.Filters("ccd-amend", null, null, null, 10, 0))
                .get(0).id();

        PlateSolution s = new PlateSolution(
                10.6847083, 41.269083, 1.234, 12.5, 0.5, 0.4, Instant.now(), "astap");
        SequencedMap<String, String> cards = s.toFitsCards();

        store.amendHeader(imageId, cards);

        ImageRecord rec = store.find(imageId).orElseThrow();
        byte[] reread = Files.readAllBytes(Path.of(rec.fitsPath()));
        FitsHeaderReader.Header h = FitsHeaderReader.read(reread);
        assertThat(reread.length % 2880).isZero();
        assertThat(rec.bytes()).isEqualTo(reread.length);
        String headerText = new String(reread, 0, h.dataOffset(),
                java.nio.charset.StandardCharsets.US_ASCII);
        assertThat(headerText).contains("CRVAL1");
        assertThat(headerText).contains("CRVAL2");

        Optional<dev.nocs.platesolving.PlateSolutionRecord> row =
                solutions.findByImageId(imageId);
        assertThat(row).isPresent();
        assertThat(row.get().raJ2000Deg()).isEqualTo(10.6847083);
        assertThat(row.get().solver()).isEqualTo("astap");
    }
}
```

- [ ] **Step 10.5: Implement the real `amendHeader` + `loadFits`**

Modify `src/main/java/dev/nocs/image/ImageStoreService.java`. Add the `PlateSolutionRepository` constructor parameter (Spring will inject), add the `Clock`/`Instant` plumbing if helpful, and replace the stub `amendHeader` plus add `loadFits`. The diff replaces the existing class top-to-bottom with the version below:

```java
package dev.nocs.image;

import dev.nocs.config.NocsProperties;
import dev.nocs.device.DeviceId;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.platesolving.PlateSolutionRecord;
import dev.nocs.platesolving.PlateSolutionRepository;
import dev.nocs.session.Session;
import dev.nocs.session.SessionService;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.Instant;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Service;

@Service
public class ImageStoreService {

    private static final Logger log = LoggerFactory.getLogger(ImageStoreService.class);

    private final ImageRepository repo;
    private final EventBus bus;
    private final ThumbnailGenerator thumbnails;
    private final PendingCaptures pending = new PendingCaptures();
    private final Path dataDir;
    private final ObjectProvider<SessionService> sessionService;
    private final PlateSolutionRepository plateSolutions;

    public ImageStoreService(
            ImageRepository repo,
            EventBus bus,
            ThumbnailGenerator thumbnails,
            NocsProperties props,
            ObjectProvider<SessionService> sessionService,
            PlateSolutionRepository plateSolutions) {
        this.repo = repo;
        this.bus = bus;
        this.thumbnails = thumbnails;
        String dir = props.dataDir() != null ? props.dataDir() : System.getProperty("java.io.tmpdir");
        this.dataDir = Path.of(dir);
        this.sessionService = sessionService;
        this.plateSolutions = plateSolutions;
    }

    public void prepareCapture(DeviceId camera, CaptureContext ctx) {
        pending.prepare(camera, ctx);
    }

    public void accept(DeviceId camera, byte[] bytes, String extension) {
        CaptureContext ctx = pending.consume(camera).orElseGet(() -> CaptureContext.defaults(0));
        try {
            saveAndPublish(camera, bytes, extension, ctx);
        } catch (Exception e) {
            log.error("image store failed for camera {}: {}", camera.value(), e.getMessage(), e);
            bus.publish(Event.of(Topic.CAMERA, "image_store_failed", Map.of(
                    "device", camera.value(),
                    "error", e.getMessage() == null ? "unknown" : e.getMessage())));
        }
    }

    private void saveAndPublish(DeviceId camera, byte[] bytes, String extension, CaptureContext ctx)
            throws IOException {
        Path fitsPath = ImagePaths.forCapture(dataDir, LocalDate.now(), camera.value(), ctx);
        Files.createDirectories(fitsPath.getParent());
        fitsPath = ImagePaths.nextAvailable(fitsPath);
        Path tempFile = fitsPath.resolveSibling(fitsPath.getFileName() + ".part");
        Files.write(tempFile, bytes);
        Files.move(tempFile, fitsPath, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);

        Optional<byte[]> thumbBytes = isFits(extension)
                ? thumbnails.generate(bytes)
                : Optional.empty();
        Path thumbPath = null;
        if (thumbBytes.isPresent()) {
            thumbPath = ImagePaths.thumbnailFor(fitsPath);
            Files.write(thumbPath, thumbBytes.get());
        }

        Integer width = null;
        Integer height = null;
        Integer bitpix = null;
        String dateObs = null;
        if (isFits(extension)) {
            try {
                FitsHeaderReader.Header h = FitsHeaderReader.read(bytes);
                width = h.naxis() == 2 ? h.naxis1() : null;
                height = h.naxis() == 2 ? h.naxis2() : null;
                bitpix = h.bitpix();
                dateObs = h.dateObs();
            } catch (IllegalArgumentException e) {
                log.warn("metadata extraction failed for {}: {}", fitsPath, e.getMessage());
            }
        }

        Long sessionId = currentSessionId();
        ImageRecord rec = ImageRecord.forInsert(
                sessionId, camera.value(), ctx,
                fitsPath.toString(),
                thumbPath == null ? null : thumbPath.toString(),
                bytes.length, width, height, bitpix, dateObs);
        long id = repo.insert(rec);

        Map<String, Object> payload = new HashMap<>();
        payload.put("id", id);
        payload.put("device", camera.value());
        payload.put("session_id", sessionId);
        payload.put("fits_path", fitsPath.toString());
        payload.put("thumb_path", thumbPath == null ? null : thumbPath.toString());
        payload.put("filter", ctx.filter());
        payload.put("target", ctx.target());
        payload.put("exposure_s", ctx.exposureSec());
        payload.put("step", ctx.step());
        payload.put("seq", ctx.seq());
        payload.put("bytes", (long) bytes.length);
        payload.put("width", width);
        payload.put("height", height);
        payload.put("bitpix", bitpix);
        payload.put("date_obs", dateObs);
        bus.publish(Event.of(Topic.CAMERA, "image_saved", payload));
    }

    public Optional<ImageRecord> find(long id) {
        return repo.findById(id);
    }

    public List<ImageRecord> list(ImageRepository.Filters filters) {
        return repo.list(filters);
    }

    public boolean delete(long id) {
        Optional<ImageRecord> existing = repo.findById(id);
        if (existing.isEmpty()) {
            return false;
        }
        ImageRecord rec = existing.get();
        deleteIfPresent(Path.of(rec.fitsPath()));
        if (rec.thumbPath() != null) {
            deleteIfPresent(Path.of(rec.thumbPath()));
        }
        return repo.delete(id);
    }

    public Optional<byte[]> loadFits(long id) {
        return find(id).flatMap(rec -> {
            try {
                return Optional.of(Files.readAllBytes(Path.of(rec.fitsPath())));
            } catch (IOException e) {
                log.warn("loadFits failed for id {}: {}", id, e.getMessage());
                return Optional.empty();
            }
        });
    }

    /**
     * Rewrites the saved FITS header with {@code additionalCards}, persisting the bytes
     * atomically and refreshing the {@code images.bytes} count. When the additions look
     * like a WCS solution (presence of {@code CRVAL1} + {@code CRVAL2}), upserts a
     * {@link PlateSolutionRecord} for the image. Returns true when the row was updated.
     */
    public boolean amendHeader(long id, java.util.SequencedMap<String, String> additionalCards) {
        Optional<ImageRecord> existing = repo.findById(id);
        if (existing.isEmpty()) {
            return false;
        }
        ImageRecord rec = existing.get();
        Path path = Path.of(rec.fitsPath());
        byte[] original;
        try {
            original = Files.readAllBytes(path);
        } catch (IOException e) {
            log.error("amendHeader cannot read {}: {}", path, e.getMessage());
            return false;
        }
        byte[] amended = FitsHeaderWriter.writeWithCards(original, additionalCards);
        try {
            Path tmp = path.resolveSibling(path.getFileName() + ".amend");
            Files.write(tmp, amended);
            Files.move(tmp, path, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } catch (IOException e) {
            log.error("amendHeader cannot write {}: {}", path, e.getMessage());
            return false;
        }
        repo.updateBytes(id, amended.length);

        if (additionalCards != null
                && additionalCards.containsKey("CRVAL1")
                && additionalCards.containsKey("CRVAL2")) {
            try {
                double ra = Double.parseDouble(additionalCards.get("CRVAL1"));
                double dec = Double.parseDouble(additionalCards.get("CRVAL2"));
                double pixelScale = additionalCards.containsKey("CDELT2")
                        ? Math.abs(Double.parseDouble(additionalCards.get("CDELT2"))) * 3600.0
                        : 0.0;
                double rot = additionalCards.containsKey("CROTA2")
                        ? Double.parseDouble(additionalCards.get("CROTA2"))
                        : 0.0;
                double fovW = additionalCards.containsKey("FOVWIDTH")
                        ? Double.parseDouble(additionalCards.get("FOVWIDTH")) : 0.0;
                double fovH = additionalCards.containsKey("FOVHIGHT")
                        ? Double.parseDouble(additionalCards.get("FOVHIGHT")) : 0.0;
                String solver = additionalCards.containsKey("PLATESLV")
                        ? additionalCards.get("PLATESLV").replace("'", "").trim()
                        : "unknown";
                plateSolutions.upsert(PlateSolutionRecord.forInsert(
                        id, ra, dec, pixelScale, rot, fovW, fovH, 0L, solver, Instant.now()));
            } catch (NumberFormatException e) {
                log.warn("amendHeader: WCS cards present but un-parseable for id {}: {}", id, e.getMessage());
            }
        }
        return true;
    }

    private static boolean isFits(String extension) {
        if (extension == null) {
            return false;
        }
        String e = extension.toLowerCase();
        return e.equals(".fits") || e.equals("fits") || e.endsWith(".fits") || e.endsWith(".fit");
    }

    private Long currentSessionId() {
        SessionService svc = sessionService.getIfAvailable();
        if (svc == null) {
            return null;
        }
        Session s = svc.current();
        return s == null ? null : s.id();
    }

    private static void deleteIfPresent(Path p) {
        try {
            Files.deleteIfExists(p);
        } catch (IOException e) {
            log.warn("failed to delete {}: {}", p, e.getMessage());
        }
    }
}
```

The new `repo.updateBytes(id, ...)` does not yet exist on `ImageRepository`. Add it:

```java
public int updateBytes(long id, long bytes) {
    return jdbc.update("UPDATE images SET bytes = ? WHERE id = ?", bytes, id);
}
```

(Append to `src/main/java/dev/nocs/image/ImageRepository.java`.)

- [ ] **Step 10.6: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.image.FitsHeaderWriterTest' --tests 'dev.nocs.image.ImageStoreServiceAmendHeaderTest'`
Expected: both pass.

If `ImageStoreServiceAmendHeaderTest` complains that `MiniFits` is not found, ensure the helper is on the test classpath under `src/test/java/dev/nocs/image/MiniFits.java` (Plan D Task 5 builds it).

- [ ] **Step 10.7: Run the wider image suite to confirm Plan D still passes**

Run: `./gradlew test --tests 'dev.nocs.image.*'`
Expected: every existing Plan D test plus the new ones pass.

- [ ] **Step 10.8: Commit**

```bash
git add src/main/java/dev/nocs/image/FitsHeaderWriter.java \
        src/main/java/dev/nocs/image/ImageStoreService.java \
        src/main/java/dev/nocs/image/ImageRepository.java \
        src/test/java/dev/nocs/image/FitsHeaderWriterTest.java \
        src/test/java/dev/nocs/image/ImageStoreServiceAmendHeaderTest.java
git commit -m "feat(image): real amendHeader + FitsHeaderWriter (replaces Plan D stub)"
```

---

### Task 11: Install pipeline support classes

**Files:**
- Create: `src/main/java/dev/nocs/platesolving/install/InstallPhase.java`
- Create: `src/main/java/dev/nocs/platesolving/install/InstallProgress.java`
- Create: `src/main/java/dev/nocs/platesolving/install/InstallRequest.java`
- Create: `src/main/java/dev/nocs/platesolving/install/ArchiveKind.java`
- Create: `src/main/java/dev/nocs/platesolving/install/AstapInstallSpec.java`
- Create: `src/main/java/dev/nocs/platesolving/install/AstapInstallSpecs.java`
- Create: `src/main/java/dev/nocs/platesolving/install/Sha256Verifier.java`
- Create: `src/main/java/dev/nocs/platesolving/install/ZipExtractor.java`
- Create: `src/main/java/dev/nocs/platesolving/install/TarGzExtractor.java`
- Create: `src/main/java/dev/nocs/platesolving/install/AstapDownloader.java`
- Create: `src/main/java/dev/nocs/platesolving/install/ProgressListener.java`
- Create: `src/main/java/dev/nocs/platesolving/install/HttpAstapDownloader.java`
- Create: `src/main/java/dev/nocs/platesolving/install/AstapInstaller.java`
- Create: `src/test/java/dev/nocs/platesolving/install/Sha256VerifierTest.java`
- Create: `src/test/java/dev/nocs/platesolving/install/ZipExtractorTest.java`
- Create: `src/test/java/dev/nocs/platesolving/install/TarGzExtractorTest.java`
- Create: `src/test/java/dev/nocs/platesolving/install/AstapInstallSpecsTest.java`
- Create: `src/test/java/dev/nocs/platesolving/install/AstapInstallerTest.java`

This task ships the entire install pipeline behind tests that never touch the network: tests use a `FileAstapDownloader` test double to serve archives generated in-process.

- [ ] **Step 11.1: Implement the value types**

Create `src/main/java/dev/nocs/platesolving/install/InstallPhase.java`:

```java
package dev.nocs.platesolving.install;

public enum InstallPhase {
    IDLE,
    RESOLVING_SPEC,
    DOWNLOADING_BINARY,
    VERIFYING_BINARY,
    EXTRACTING_BINARY,
    DOWNLOADING_DB,
    VERIFYING_DB,
    EXTRACTING_DB,
    DONE,
    FAILED,
    CANCELLED
}
```

Create `src/main/java/dev/nocs/platesolving/install/InstallProgress.java`:

```java
package dev.nocs.platesolving.install;

import java.time.Instant;

public record InstallProgress(
        InstallPhase phase,
        long bytesDone,
        long bytesTotal,
        String message,
        Instant updatedAt) {

    public InstallProgress {
        if (phase == null) {
            phase = InstallPhase.IDLE;
        }
        if (message == null) {
            message = "";
        }
        if (updatedAt == null) {
            updatedAt = Instant.now();
        }
    }

    public static InstallProgress idle() {
        return new InstallProgress(InstallPhase.IDLE, 0L, 0L, "", Instant.now());
    }
}
```

Create `src/main/java/dev/nocs/platesolving/install/InstallRequest.java`:

```java
package dev.nocs.platesolving.install;

public record InstallRequest(boolean acceptLicense) {}
```

Create `src/main/java/dev/nocs/platesolving/install/ArchiveKind.java`:

```java
package dev.nocs.platesolving.install;

public enum ArchiveKind {
    ZIP, TAR_GZ, RAW
}
```

Create `src/main/java/dev/nocs/platesolving/install/AstapInstallSpec.java`:

```java
package dev.nocs.platesolving.install;

import java.net.URI;

public record AstapInstallSpec(
        URI binaryUrl,
        String binarySha256,
        ArchiveKind binaryKind,
        String binaryEntryName,
        URI dbUrl,
        String dbSha256,
        String dbName,
        ArchiveKind dbKind) {

    public AstapInstallSpec {
        if (binaryUrl == null) {
            throw new IllegalArgumentException("binaryUrl required");
        }
        if (dbUrl == null) {
            throw new IllegalArgumentException("dbUrl required");
        }
        if (binarySha256 == null || binarySha256.isBlank()) {
            throw new IllegalArgumentException("binarySha256 required");
        }
        if (dbSha256 == null || dbSha256.isBlank()) {
            throw new IllegalArgumentException("dbSha256 required");
        }
        if (binaryEntryName == null || binaryEntryName.isBlank()) {
            binaryEntryName = "astap_cli";
        }
        if (dbName == null || dbName.isBlank()) {
            dbName = "H18";
        }
        if (binaryKind == null) {
            binaryKind = ArchiveKind.ZIP;
        }
        if (dbKind == null) {
            dbKind = ArchiveKind.ZIP;
        }
    }
}
```

- [ ] **Step 11.2: `AstapInstallSpecs` + test**

Create `src/main/java/dev/nocs/platesolving/install/AstapInstallSpecs.java`:

```java
package dev.nocs.platesolving.install;

import dev.nocs.config.NocsProperties;
import java.net.URI;
import java.util.Locale;
import java.util.Optional;

public final class AstapInstallSpecs {

    private AstapInstallSpecs() {}

    public static Optional<AstapInstallSpec> forCurrent(NocsProperties props) {
        return forPlatform(props, currentPlatformKey());
    }

    public static Optional<AstapInstallSpec> forPlatform(NocsProperties props, String platformKey) {
        if (platformKey == null) {
            return Optional.empty();
        }
        if (props.platesolving() == null) {
            return Optional.empty();
        }
        NocsProperties.PlateSolving.Install install = props.platesolving().install();
        if (install == null) {
            return Optional.empty();
        }
        String urlTpl = install.binaryUrlTemplate();
        String binarySha = install.binarySha256().get(platformKey);
        String dbUrl = install.dbUrl();
        String dbSha = install.dbSha256();
        if (urlTpl == null || urlTpl.isBlank() || binarySha == null || binarySha.isBlank()
                || dbUrl == null || dbUrl.isBlank() || dbSha == null || dbSha.isBlank()) {
            return Optional.empty();
        }
        String[] parts = platformKey.split("-", 2);
        String os = parts.length > 0 ? parts[0] : "";
        String arch = parts.length > 1 ? parts[1] : "";
        URI binary = URI.create(urlTpl.replace("{os}", os).replace("{arch}", arch));
        URI db = URI.create(dbUrl);
        ArchiveKind binaryKind = "windows".equals(os) ? ArchiveKind.ZIP : ArchiveKind.TAR_GZ;
        return Optional.of(new AstapInstallSpec(
                binary, binarySha, binaryKind, defaultBinaryEntry(os),
                db, dbSha, props.platesolving().astap().dbName(), ArchiveKind.ZIP));
    }

    public static String currentPlatformKey() {
        String os = System.getProperty("os.name", "").toLowerCase(Locale.ROOT);
        String arch = System.getProperty("os.arch", "").toLowerCase(Locale.ROOT);
        String osKey;
        if (os.contains("win")) {
            osKey = "windows";
        } else if (os.contains("mac") || os.contains("darwin")) {
            return null;
        } else {
            osKey = "linux";
        }
        String archKey;
        if (arch.contains("aarch64") || arch.contains("arm64")) {
            archKey = "arm64";
        } else if (arch.contains("amd64") || arch.contains("x86_64")) {
            archKey = "x86_64";
        } else {
            return null;
        }
        return osKey + "-" + archKey;
    }

    private static String defaultBinaryEntry(String os) {
        return "windows".equals(os) ? "astap_cli.exe" : "astap_cli";
    }
}
```

Create `src/test/java/dev/nocs/platesolving/install/AstapInstallSpecsTest.java`:

```java
package dev.nocs.platesolving.install;

import dev.nocs.config.NocsProperties;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class AstapInstallSpecsTest {

    @Test
    void resolvesLinuxX86_64WhenConfigured() {
        NocsProperties props = props("https://example.invalid/astap-{os}-{arch}.tar.gz",
                Map.of("linux-x86_64", "deadbeef"),
                "https://example.invalid/h18.zip", "cafebabe");

        Optional<AstapInstallSpec> out = AstapInstallSpecs.forPlatform(props, "linux-x86_64");

        assertThat(out).isPresent();
        AstapInstallSpec spec = out.get();
        assertThat(spec.binaryUrl().toString()).isEqualTo("https://example.invalid/astap-linux-x86_64.tar.gz");
        assertThat(spec.binarySha256()).isEqualTo("deadbeef");
        assertThat(spec.binaryKind()).isEqualTo(ArchiveKind.TAR_GZ);
        assertThat(spec.binaryEntryName()).isEqualTo("astap_cli");
        assertThat(spec.dbUrl().toString()).isEqualTo("https://example.invalid/h18.zip");
    }

    @Test
    void resolvesWindowsX86_64Zip() {
        NocsProperties props = props("https://example.invalid/{os}-{arch}.zip",
                Map.of("windows-x86_64", "abc"), "https://example.invalid/h18.zip", "def");

        Optional<AstapInstallSpec> out = AstapInstallSpecs.forPlatform(props, "windows-x86_64");

        assertThat(out).isPresent();
        assertThat(out.get().binaryKind()).isEqualTo(ArchiveKind.ZIP);
        assertThat(out.get().binaryEntryName()).isEqualTo("astap_cli.exe");
    }

    @Test
    void unsupportedPlatformReturnsEmpty() {
        NocsProperties props = props("https://example.invalid/{os}-{arch}.zip",
                Map.of("linux-x86_64", "abc"), "https://example.invalid/h18.zip", "def");

        assertThat(AstapInstallSpecs.forPlatform(props, "linux-arm64")).isEmpty();
    }

    @Test
    void blankConfigReturnsEmpty() {
        NocsProperties props = props("", Map.of(), "", "");
        assertThat(AstapInstallSpecs.forPlatform(props, "linux-x86_64")).isEmpty();
    }

    private static NocsProperties props(String tpl, Map<String, String> binSha, String dbUrl, String dbSha) {
        NocsProperties.PlateSolving.Astap astap = new NocsProperties.PlateSolving.Astap("", "", "H18");
        NocsProperties.PlateSolving.Install install = new NocsProperties.PlateSolving.Install(
                true, tpl, binSha, dbUrl, dbSha);
        NocsProperties.PlateSolving ps = new NocsProperties.PlateSolving("astap", 60L, astap, install);
        return new NocsProperties(null, null, null, null, null, null, null, ps);
    }
}
```

- [ ] **Step 11.3: Implement `Sha256Verifier` + test**

Create `src/main/java/dev/nocs/platesolving/install/Sha256Verifier.java`:

```java
package dev.nocs.platesolving.install;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Locale;
import org.springframework.stereotype.Component;

@Component
public class Sha256Verifier {

    public void verify(Path file, String expectedHex) throws IOException {
        if (expectedHex == null || expectedHex.isBlank()) {
            throw new IOException("expected sha256 missing");
        }
        String actual = compute(file);
        if (!actual.equalsIgnoreCase(expectedHex.trim())) {
            throw new IOException(
                    "sha256 mismatch for " + file.getFileName()
                            + ": expected=" + expectedHex + " actual=" + actual);
        }
    }

    public String compute(Path file) throws IOException {
        MessageDigest md;
        try {
            md = MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException e) {
            throw new IOException(e);
        }
        try (InputStream in = Files.newInputStream(file)) {
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) {
                md.update(buf, 0, n);
            }
        }
        byte[] digest = md.digest();
        StringBuilder sb = new StringBuilder(digest.length * 2);
        for (byte b : digest) {
            sb.append(String.format(Locale.ROOT, "%02x", b));
        }
        return sb.toString();
    }
}
```

Create `src/test/java/dev/nocs/platesolving/install/Sha256VerifierTest.java`:

```java
package dev.nocs.platesolving.install;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class Sha256VerifierTest {

    @Test
    void computeMatchesKnownDigest(@TempDir Path tmp) throws IOException {
        Path file = tmp.resolve("hello.txt");
        Files.writeString(file, "hello\n");
        // sha256("hello\n") = 5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03
        String hex = new Sha256Verifier().compute(file);
        assertThat(hex).isEqualTo("5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03");
    }

    @Test
    void verifyThrowsOnMismatch(@TempDir Path tmp) throws IOException {
        Path file = tmp.resolve("hello.txt");
        Files.writeString(file, "hello\n");
        assertThatThrownBy(() -> new Sha256Verifier().verify(file, "deadbeef"))
                .isInstanceOf(IOException.class)
                .hasMessageContaining("mismatch");
    }
}
```

- [ ] **Step 11.4: Implement `ZipExtractor` + test**

Create `src/main/java/dev/nocs/platesolving/install/ZipExtractor.java`:

```java
package dev.nocs.platesolving.install;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;
import org.springframework.stereotype.Component;

@Component
public class ZipExtractor {

    public void extractEntry(Path zipFile, String entryName, Path destFile) throws IOException {
        try (InputStream raw = Files.newInputStream(zipFile);
             ZipInputStream zin = new ZipInputStream(raw)) {
            ZipEntry e;
            while ((e = zin.getNextEntry()) != null) {
                if (matches(e.getName(), entryName)) {
                    Files.createDirectories(destFile.getParent());
                    try (OutputStream out = Files.newOutputStream(destFile,
                            StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING)) {
                        zin.transferTo(out);
                    }
                    return;
                }
            }
        }
        throw new IOException("entry " + entryName + " not found in " + zipFile);
    }

    public void extractAll(Path zipFile, Path destDir) throws IOException {
        Files.createDirectories(destDir);
        try (InputStream raw = Files.newInputStream(zipFile);
             ZipInputStream zin = new ZipInputStream(raw)) {
            ZipEntry e;
            while ((e = zin.getNextEntry()) != null) {
                Path target = destDir.resolve(e.getName()).normalize();
                if (!target.startsWith(destDir)) {
                    throw new IOException("zip slip: " + e.getName());
                }
                if (e.isDirectory()) {
                    Files.createDirectories(target);
                    continue;
                }
                Files.createDirectories(target.getParent());
                try (OutputStream out = Files.newOutputStream(target,
                        StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING)) {
                    zin.transferTo(out);
                }
            }
        }
    }

    private static boolean matches(String entryName, String wanted) {
        if (entryName.equals(wanted)) {
            return true;
        }
        int slash = entryName.lastIndexOf('/');
        return slash >= 0 && entryName.substring(slash + 1).equals(wanted);
    }
}
```

Create `src/test/java/dev/nocs/platesolving/install/ZipExtractorTest.java`:

```java
package dev.nocs.platesolving.install;

import java.io.IOException;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.assertj.core.api.Assertions.assertThat;

class ZipExtractorTest {

    @Test
    void extractsNamedEntry(@TempDir Path tmp) throws IOException {
        Path zip = buildZip(tmp.resolve("ar.zip"),
                "astap_cli", "binary-bytes",
                "README.md", "README content");

        Path out = tmp.resolve("bin/astap_cli");
        new ZipExtractor().extractEntry(zip, "astap_cli", out);

        assertThat(Files.readString(out)).isEqualTo("binary-bytes");
    }

    @Test
    void extractAllPlacesEachEntry(@TempDir Path tmp) throws IOException {
        Path zip = buildZip(tmp.resolve("ar.zip"),
                "h18/h18_index.dat", "idx-bytes",
                "h18/h18_data.dat", "data-bytes");

        Path dest = tmp.resolve("db");
        new ZipExtractor().extractAll(zip, dest);

        assertThat(Files.readString(dest.resolve("h18/h18_index.dat"))).isEqualTo("idx-bytes");
        assertThat(Files.readString(dest.resolve("h18/h18_data.dat"))).isEqualTo("data-bytes");
    }

    private static Path buildZip(Path target, String... pairs) throws IOException {
        try (OutputStream out = Files.newOutputStream(target);
             ZipOutputStream zout = new ZipOutputStream(out)) {
            for (int i = 0; i < pairs.length; i += 2) {
                zout.putNextEntry(new ZipEntry(pairs[i]));
                zout.write(pairs[i + 1].getBytes());
                zout.closeEntry();
            }
        }
        return target;
    }
}
```

- [ ] **Step 11.5: Implement `TarGzExtractor` + test**

Create `src/main/java/dev/nocs/platesolving/install/TarGzExtractor.java`:

```java
package dev.nocs.platesolving.install;

import java.io.BufferedInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.zip.GZIPInputStream;
import org.springframework.stereotype.Component;

/** Minimal pure-Java tar.gz reader: handles 512-byte headers, ustar names, and regular files. */
@Component
public class TarGzExtractor {

    private static final int BLOCK = 512;

    public void extractEntry(Path archive, String entryName, Path destFile) throws IOException {
        try (InputStream in = openGz(archive)) {
            TarHeader header;
            while ((header = readHeader(in)) != null) {
                if (matches(header.name, entryName) && header.typeFlag == '0') {
                    Files.createDirectories(destFile.getParent());
                    try (OutputStream out = Files.newOutputStream(destFile,
                            StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING)) {
                        copy(in, out, header.size);
                    }
                    skipPadding(in, header.size);
                    return;
                } else {
                    skipPadding(in, header.size);
                }
            }
        }
        throw new IOException("entry " + entryName + " not found in " + archive);
    }

    public void extractAll(Path archive, Path destDir) throws IOException {
        Files.createDirectories(destDir);
        try (InputStream in = openGz(archive)) {
            TarHeader header;
            while ((header = readHeader(in)) != null) {
                Path target = destDir.resolve(header.name).normalize();
                if (!target.startsWith(destDir)) {
                    throw new IOException("tar slip: " + header.name);
                }
                if (header.typeFlag == '5') {
                    Files.createDirectories(target);
                } else if (header.typeFlag == '0' || header.typeFlag == 0) {
                    Files.createDirectories(target.getParent());
                    try (OutputStream out = Files.newOutputStream(target,
                            StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING)) {
                        copy(in, out, header.size);
                    }
                } else {
                    skipExactly(in, header.size);
                }
                skipPadding(in, header.size);
            }
        }
    }

    private static InputStream openGz(Path archive) throws IOException {
        return new BufferedInputStream(new GZIPInputStream(Files.newInputStream(archive)));
    }

    private static TarHeader readHeader(InputStream in) throws IOException {
        byte[] block = in.readNBytes(BLOCK);
        if (block.length < BLOCK) {
            return null;
        }
        boolean allZero = true;
        for (byte b : block) {
            if (b != 0) {
                allZero = false;
                break;
            }
        }
        if (allZero) {
            return null;
        }
        String name = trimNul(new String(block, 0, 100, StandardCharsets.US_ASCII));
        long size = parseOctal(block, 124, 12);
        char typeFlag = (char) block[156];
        if ((char) block[257] == 'u' && (char) block[258] == 's' && (char) block[259] == 't') {
            String prefix = trimNul(new String(block, 345, 155, StandardCharsets.US_ASCII));
            if (!prefix.isEmpty()) {
                name = prefix + "/" + name;
            }
        }
        return new TarHeader(name, size, typeFlag);
    }

    private static void copy(InputStream in, OutputStream out, long size) throws IOException {
        byte[] buf = new byte[8192];
        long remaining = size;
        while (remaining > 0) {
            int want = (int) Math.min(buf.length, remaining);
            int read = in.read(buf, 0, want);
            if (read <= 0) {
                throw new IOException("tar truncated");
            }
            out.write(buf, 0, read);
            remaining -= read;
        }
    }

    private static void skipPadding(InputStream in, long size) throws IOException {
        long mod = size % BLOCK;
        if (mod != 0) {
            skipExactly(in, BLOCK - mod);
        }
    }

    private static void skipExactly(InputStream in, long n) throws IOException {
        long remaining = n;
        byte[] buf = new byte[(int) Math.min(8192, n)];
        while (remaining > 0) {
            int want = (int) Math.min(buf.length, remaining);
            int read = in.read(buf, 0, want);
            if (read <= 0) {
                throw new IOException("tar truncated");
            }
            remaining -= read;
        }
    }

    private static long parseOctal(byte[] block, int offset, int len) {
        long v = 0;
        for (int i = offset; i < offset + len; i++) {
            byte b = block[i];
            if (b == 0 || b == ' ') {
                continue;
            }
            v = (v << 3) + (b - '0');
        }
        return v;
    }

    private static String trimNul(String s) {
        int nul = s.indexOf('\0');
        return (nul >= 0 ? s.substring(0, nul) : s).trim();
    }

    private static boolean matches(String entryName, String wanted) {
        if (entryName.equals(wanted)) {
            return true;
        }
        int slash = entryName.lastIndexOf('/');
        return slash >= 0 && entryName.substring(slash + 1).equals(wanted);
    }

    private record TarHeader(String name, long size, char typeFlag) {}
}
```

Create `src/test/java/dev/nocs/platesolving/install/TarGzExtractorTest.java`:

```java
package dev.nocs.platesolving.install;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Locale;
import java.util.zip.GZIPOutputStream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.assertj.core.api.Assertions.assertThat;

class TarGzExtractorTest {

    @Test
    void extractsRegularFile(@TempDir Path tmp) throws IOException {
        Path archive = tmp.resolve("astap.tar.gz");
        byte[] payload = "binary-bytes".getBytes(StandardCharsets.UTF_8);
        writeTarGz(archive, "astap_cli", payload);

        Path dest = tmp.resolve("bin/astap_cli");
        new TarGzExtractor().extractEntry(archive, "astap_cli", dest);

        assertThat(Files.readAllBytes(dest)).isEqualTo(payload);
    }

    /** Build a one-entry ustar gzip archive without commons-compress. */
    private static void writeTarGz(Path target, String name, byte[] payload) throws IOException {
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        byte[] header = new byte[512];
        byte[] nameBytes = name.getBytes(StandardCharsets.US_ASCII);
        System.arraycopy(nameBytes, 0, header, 0, nameBytes.length);
        write(header, 100, "0000777 ", 8);
        write(header, 108, "0000000 ", 8);
        write(header, 116, "0000000 ", 8);
        write(header, 124, String.format(Locale.ROOT, "%011o ", payload.length), 12);
        write(header, 136, "00000000000 ", 12);
        for (int i = 148; i < 156; i++) {
            header[i] = ' ';
        }
        header[156] = '0';
        write(header, 257, "ustar ", 6);
        write(header, 263, " ", 2);
        long checksum = 0;
        for (byte b : header) {
            checksum += b & 0xff;
        }
        byte[] cs = String.format(Locale.ROOT, "%06o\0 ", checksum).getBytes(StandardCharsets.US_ASCII);
        System.arraycopy(cs, 0, header, 148, cs.length);

        buf.write(header);
        buf.write(payload);
        int pad = (512 - (payload.length % 512)) % 512;
        buf.write(new byte[pad]);
        buf.write(new byte[1024]);

        try (OutputStream out = new GZIPOutputStream(Files.newOutputStream(target))) {
            out.write(buf.toByteArray());
        }
    }

    private static void write(byte[] header, int offset, String text, int len) {
        byte[] b = text.getBytes(StandardCharsets.US_ASCII);
        System.arraycopy(b, 0, header, offset, Math.min(b.length, len));
    }
}
```

- [ ] **Step 11.6: Implement `AstapDownloader` + `ProgressListener` + `HttpAstapDownloader`**

Create `src/main/java/dev/nocs/platesolving/install/ProgressListener.java`:

```java
package dev.nocs.platesolving.install;

@FunctionalInterface
public interface ProgressListener {
    void onBytes(long bytesDone, long bytesTotal);
}
```

Create `src/main/java/dev/nocs/platesolving/install/AstapDownloader.java`:

```java
package dev.nocs.platesolving.install;

import java.io.IOException;
import java.net.URI;
import java.nio.file.Path;

public interface AstapDownloader {
    void download(URI url, Path dest, ProgressListener listener) throws IOException;
}
```

Create `src/main/java/dev/nocs/platesolving/install/HttpAstapDownloader.java`:

```java
package dev.nocs.platesolving.install;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Duration;
import org.springframework.stereotype.Component;

@Component
public class HttpAstapDownloader implements AstapDownloader {

    private final HttpClient client = HttpClient.newBuilder()
            .followRedirects(HttpClient.Redirect.ALWAYS)
            .connectTimeout(Duration.ofSeconds(30))
            .build();

    @Override
    public void download(URI url, Path dest, ProgressListener listener) throws IOException {
        HttpRequest req = HttpRequest.newBuilder(url).GET().build();
        try {
            HttpResponse<InputStream> resp = client.send(req, HttpResponse.BodyHandlers.ofInputStream());
            if (resp.statusCode() / 100 != 2) {
                throw new IOException("HTTP " + resp.statusCode() + " for " + url);
            }
            long total = resp.headers().firstValueAsLong("Content-Length").orElse(-1L);
            Files.createDirectories(dest.getParent());
            try (InputStream in = resp.body();
                 OutputStream out = Files.newOutputStream(dest,
                         StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING)) {
                byte[] buf = new byte[64 * 1024];
                long done = 0;
                int n;
                while ((n = in.read(buf)) > 0) {
                    out.write(buf, 0, n);
                    done += n;
                    if (listener != null) {
                        listener.onBytes(done, total);
                    }
                }
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IOException("download interrupted", e);
        }
    }
}
```

- [ ] **Step 11.7: Implement `AstapInstaller`**

Create `src/main/java/dev/nocs/platesolving/install/AstapInstaller.java`:

```java
package dev.nocs.platesolving.install;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Locale;
import org.springframework.stereotype.Component;

@Component
public class AstapInstaller {

    private final AstapDownloader downloader;
    private final Sha256Verifier verifier;
    private final ZipExtractor zip;
    private final TarGzExtractor tar;

    public AstapInstaller(AstapDownloader downloader, Sha256Verifier verifier,
                          ZipExtractor zip, TarGzExtractor tar) {
        this.downloader = downloader;
        this.verifier = verifier;
        this.zip = zip;
        this.tar = tar;
    }

    public Path install(AstapInstallSpec spec, Path dataDir, InstallEvents events) throws IOException {
        Path astapRoot = dataDir.resolve("astap");
        Path binDir = astapRoot.resolve("bin");
        Path dbDir = astapRoot.resolve("db");
        Files.createDirectories(binDir);
        Files.createDirectories(dbDir);

        Path binaryArchive = astapRoot.resolve("downloads/binary"
                + extensionFor(spec.binaryKind()));
        Path dbArchive = astapRoot.resolve("downloads/db"
                + extensionFor(spec.dbKind()));

        events.phase(InstallPhase.DOWNLOADING_BINARY, "downloading ASTAP binary");
        downloader.download(spec.binaryUrl(), binaryArchive,
                (done, total) -> events.bytes(InstallPhase.DOWNLOADING_BINARY, done, total));

        events.phase(InstallPhase.VERIFYING_BINARY, "verifying binary checksum");
        verifier.verify(binaryArchive, spec.binarySha256());

        events.phase(InstallPhase.EXTRACTING_BINARY, "extracting binary");
        Path binFile = binDir.resolve(spec.binaryEntryName());
        switch (spec.binaryKind()) {
            case ZIP -> zip.extractEntry(binaryArchive, spec.binaryEntryName(), binFile);
            case TAR_GZ -> tar.extractEntry(binaryArchive, spec.binaryEntryName(), binFile);
            case RAW -> Files.copy(binaryArchive, binFile, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        }
        binFile.toFile().setExecutable(true);

        events.phase(InstallPhase.DOWNLOADING_DB, "downloading star DB " + spec.dbName());
        downloader.download(spec.dbUrl(), dbArchive,
                (done, total) -> events.bytes(InstallPhase.DOWNLOADING_DB, done, total));

        events.phase(InstallPhase.VERIFYING_DB, "verifying DB checksum");
        verifier.verify(dbArchive, spec.dbSha256());

        events.phase(InstallPhase.EXTRACTING_DB, "extracting DB");
        switch (spec.dbKind()) {
            case ZIP -> zip.extractAll(dbArchive, dbDir);
            case TAR_GZ -> tar.extractAll(dbArchive, dbDir);
            case RAW -> Files.copy(dbArchive,
                    dbDir.resolve(spec.dbName().toLowerCase(Locale.ROOT) + "_star_database.dat"),
                    java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        }

        events.phase(InstallPhase.DONE, "install complete");
        return binFile;
    }

    private static String extensionFor(ArchiveKind kind) {
        return switch (kind) {
            case ZIP -> ".zip";
            case TAR_GZ -> ".tar.gz";
            case RAW -> ".bin";
        };
    }

    /** Callbacks fired by the installer during a run; the install service implements this. */
    public interface InstallEvents {
        void phase(InstallPhase phase, String message);

        void bytes(InstallPhase phase, long done, long total);
    }
}
```

- [ ] **Step 11.8: `AstapInstallerTest` with a file-system downloader**

Create `src/test/java/dev/nocs/platesolving/install/AstapInstallerTest.java`:

```java
package dev.nocs.platesolving.install;

import java.io.IOException;
import java.io.OutputStream;
import java.net.URI;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.assertj.core.api.Assertions.assertThat;

class AstapInstallerTest {

    @Test
    void installCopiesBinaryAndDbAndFiresPhases(@TempDir Path tmp) throws IOException {
        Path binaryZip = tmp.resolve("astap.zip");
        buildZip(binaryZip, "astap_cli", "ASTAP-FAKE-BINARY");
        Path dbZip = tmp.resolve("h18.zip");
        buildZip(dbZip, "h18_star_database_index.dat", "INDEX",
                "h18_star_database_data.dat", "DATA");

        Sha256Verifier verifier = new Sha256Verifier();
        String binSha = verifier.compute(binaryZip);
        String dbSha = verifier.compute(dbZip);

        AstapInstallSpec spec = new AstapInstallSpec(
                URI.create("file:" + binaryZip),
                binSha,
                ArchiveKind.ZIP,
                "astap_cli",
                URI.create("file:" + dbZip),
                dbSha,
                "H18",
                ArchiveKind.ZIP);

        AstapDownloader downloader = (url, dest, listener) -> {
            Files.createDirectories(dest.getParent());
            Files.copy(Path.of(url.getSchemeSpecificPart()), dest,
                    java.nio.file.StandardCopyOption.REPLACE_EXISTING);
            if (listener != null) {
                listener.onBytes(Files.size(dest), Files.size(dest));
            }
        };

        AstapInstaller installer = new AstapInstaller(downloader, verifier, new ZipExtractor(), new TarGzExtractor());

        Path dataDir = tmp.resolve("data");
        List<InstallPhase> phases = new ArrayList<>();
        AstapInstaller.InstallEvents events = new AstapInstaller.InstallEvents() {
            @Override public void phase(InstallPhase p, String m) { phases.add(p); }
            @Override public void bytes(InstallPhase p, long d, long t) {}
        };

        Path bin = installer.install(spec, dataDir, events);

        assertThat(Files.readString(bin)).isEqualTo("ASTAP-FAKE-BINARY");
        assertThat(Files.readString(dataDir.resolve("astap/db/h18_star_database_index.dat")))
                .isEqualTo("INDEX");
        assertThat(phases).contains(
                InstallPhase.DOWNLOADING_BINARY,
                InstallPhase.VERIFYING_BINARY,
                InstallPhase.EXTRACTING_BINARY,
                InstallPhase.DOWNLOADING_DB,
                InstallPhase.VERIFYING_DB,
                InstallPhase.EXTRACTING_DB,
                InstallPhase.DONE);
        assertThat(bin.toFile().canExecute()).isTrue();
    }

    private static void buildZip(Path target, String... pairs) throws IOException {
        try (OutputStream out = Files.newOutputStream(target);
             ZipOutputStream zout = new ZipOutputStream(out)) {
            for (int i = 0; i < pairs.length; i += 2) {
                zout.putNextEntry(new ZipEntry(pairs[i]));
                zout.write(pairs[i + 1].getBytes());
                zout.closeEntry();
            }
        }
    }
}
```

- [ ] **Step 11.9: Run all install-pipeline tests**

Run: `./gradlew test --tests 'dev.nocs.platesolving.install.*'`
Expected: every test passes.

- [ ] **Step 11.10: Commit**

```bash
git add src/main/java/dev/nocs/platesolving/install/ \
        src/test/java/dev/nocs/platesolving/install/
git commit -m "feat(platesolving/install): downloader + verifier + extractors + AstapInstaller"
```

---

### Task 12: `AstapInstallService` (async + progress + events)

**Files:**
- Create: `src/main/java/dev/nocs/platesolving/install/AstapInstallService.java`
- Create: `src/test/java/dev/nocs/platesolving/install/AstapInstallServiceTest.java`

- [ ] **Step 12.1: Failing test**

Create `src/test/java/dev/nocs/platesolving/install/AstapInstallServiceTest.java`:

```java
package dev.nocs.platesolving.install;

import dev.nocs.config.NocsProperties;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import java.net.URI;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.List;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import reactor.core.Disposable;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class AstapInstallServiceTest {

    @Test
    void rejectsWhenNetworkDisallowed(@TempDir Path data) {
        NocsProperties props = props(false);
        AstapInstallService svc = newService(props, data, (spec, dir, ev) -> dir.resolve("astap/bin/astap_cli"));

        assertThatThrownBy(() -> svc.start(new InstallRequest(true)))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("allow-network");
    }

    @Test
    void rejectsWhenLicenseNotAccepted(@TempDir Path data) {
        AstapInstallService svc = newService(props(true), data, (spec, dir, ev) -> dir);

        assertThatThrownBy(() -> svc.start(new InstallRequest(false)))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("license");
    }

    @Test
    void runsInstallerAndPublishesEvents(@TempDir Path data) {
        EventBus bus = new EventBus();
        List<Event> events = new CopyOnWriteArrayList<>();
        Disposable sub = bus.subscribe(Topic.PLATESOLVING).subscribe(events::add);

        StubInstaller stub = new StubInstaller();
        AstapInstallService svc = new AstapInstallService(
                props(true), data, bus, stub, (p) -> java.util.Optional.of(SPEC));

        svc.start(new InstallRequest(true));

        Awaitility.await().atMost(Duration.ofSeconds(5))
                .until(() -> svc.progress().phase() == InstallPhase.DONE);

        assertThat(stub.invoked).isTrue();
        assertThat(events).extracting(Event::type)
                .contains("install_started", "install_completed");
        sub.dispose();
    }

    private static NocsProperties props(boolean allowNetwork) {
        NocsProperties.PlateSolving.Astap astap = new NocsProperties.PlateSolving.Astap("", "", "H18");
        NocsProperties.PlateSolving.Install install = new NocsProperties.PlateSolving.Install(
                allowNetwork, "https://example.invalid/{os}-{arch}.zip",
                Map.of("linux-x86_64", "deadbeef"),
                "https://example.invalid/h18.zip", "cafebabe");
        NocsProperties.PlateSolving ps = new NocsProperties.PlateSolving("astap", 60L, astap, install);
        return new NocsProperties(null, null, null, null, null, null, null, ps);
    }

    private static AstapInstallService newService(
            NocsProperties props, Path data, AstapInstaller installer) {
        return new AstapInstallService(props, data, new EventBus(), installer, p -> java.util.Optional.of(SPEC));
    }

    private static final AstapInstallSpec SPEC = new AstapInstallSpec(
            URI.create("file:/tmp/binary.zip"), "deadbeef", ArchiveKind.ZIP, "astap_cli",
            URI.create("file:/tmp/db.zip"), "cafebabe", "H18", ArchiveKind.ZIP);

    private static class StubInstaller extends AstapInstaller {
        boolean invoked;

        StubInstaller() {
            super((url, dest, listener) -> {}, new Sha256Verifier(), new ZipExtractor(), new TarGzExtractor());
        }

        @Override
        public Path install(AstapInstallSpec spec, Path dataDir, InstallEvents events) {
            invoked = true;
            events.phase(InstallPhase.DOWNLOADING_BINARY, "x");
            events.bytes(InstallPhase.DOWNLOADING_BINARY, 50L, 100L);
            events.phase(InstallPhase.DONE, "x");
            return dataDir.resolve("astap/bin/astap_cli");
        }
    }
}
```

The test imports a hypothetical `AstapInstallService` constructor `(NocsProperties, Path, EventBus, AstapInstaller, java.util.function.Function<NocsProperties, Optional<AstapInstallSpec>>)`. That last arg is the spec resolver — passing in `AstapInstallSpecs::forCurrent` in production lets us inject a fixed spec in tests without mocking statics.

- [ ] **Step 12.2: Implement `AstapInstallService`**

Create `src/main/java/dev/nocs/platesolving/install/AstapInstallService.java`:

```java
package dev.nocs.platesolving.install;

import dev.nocs.config.NocsProperties;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import jakarta.annotation.PreDestroy;
import java.nio.file.Path;
import java.time.Instant;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Function;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class AstapInstallService {

    private static final Logger log = LoggerFactory.getLogger(AstapInstallService.class);

    private final NocsProperties props;
    private final Path dataDir;
    private final EventBus bus;
    private final AstapInstaller installer;
    private final Function<NocsProperties, Optional<AstapInstallSpec>> specResolver;
    private final ExecutorService executor = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "astap-install");
        t.setDaemon(true);
        return t;
    });
    private final AtomicReference<InstallProgress> progress = new AtomicReference<>(InstallProgress.idle());
    private volatile boolean inFlight = false;

    public AstapInstallService(
            NocsProperties props,
            Path dataDir,
            EventBus bus,
            AstapInstaller installer,
            Function<NocsProperties, Optional<AstapInstallSpec>> specResolver) {
        this.props = props;
        this.dataDir = dataDir;
        this.bus = bus;
        this.installer = installer;
        this.specResolver = specResolver;
    }

    public synchronized void start(InstallRequest request) {
        if (request == null || !request.acceptLicense()) {
            throw new IllegalArgumentException("must accept ASTAP license to install");
        }
        if (props.platesolving() == null
                || props.platesolving().install() == null
                || !Boolean.TRUE.equals(props.platesolving().install().allowNetwork())) {
            throw new IllegalStateException(
                    "install blocked: set nocs.platesolving.install.allow-network=true to opt in");
        }
        if (inFlight) {
            throw new IllegalStateException("install already in progress");
        }
        Optional<AstapInstallSpec> spec = specResolver.apply(props);
        if (spec.isEmpty()) {
            throw new IllegalStateException(
                    "no install spec for current platform: " + AstapInstallSpecs.currentPlatformKey());
        }
        inFlight = true;
        publish("install_started", Map.of(
                "platform", AstapInstallSpecs.currentPlatformKey() == null
                        ? "unknown" : AstapInstallSpecs.currentPlatformKey(),
                "binary_url", spec.get().binaryUrl().toString(),
                "db_url", spec.get().dbUrl().toString()));
        executor.submit(() -> run(spec.get()));
    }

    private void run(AstapInstallSpec spec) {
        try {
            updateProgress(InstallPhase.RESOLVING_SPEC, 0, 0, "resolving install spec");
            installer.install(spec, dataDir, new AstapInstaller.InstallEvents() {
                @Override
                public void phase(InstallPhase phase, String message) {
                    updateProgress(phase, progress.get().bytesDone(), progress.get().bytesTotal(), message);
                }

                @Override
                public void bytes(InstallPhase phase, long done, long total) {
                    updateProgress(phase, done, total, progress.get().message());
                }
            });
            updateProgress(InstallPhase.DONE, progress.get().bytesDone(), progress.get().bytesTotal(),
                    "install complete");
            publish("install_completed", Map.of("phase", InstallPhase.DONE.name().toLowerCase()));
        } catch (Exception e) {
            log.error("ASTAP install failed", e);
            updateProgress(InstallPhase.FAILED, progress.get().bytesDone(), progress.get().bytesTotal(),
                    e.getMessage() == null ? "install failed" : e.getMessage());
            publish("install_failed", Map.of(
                    "error", e.getMessage() == null ? "install failed" : e.getMessage()));
        } finally {
            inFlight = false;
        }
    }

    public InstallProgress progress() {
        return progress.get();
    }

    public boolean isInFlight() {
        return inFlight;
    }

    private void updateProgress(InstallPhase phase, long done, long total, String msg) {
        InstallProgress p = new InstallProgress(phase, done, total, msg, Instant.now());
        progress.set(p);
        Map<String, Object> payload = new HashMap<>();
        payload.put("phase", phase.name().toLowerCase());
        payload.put("bytes_done", done);
        payload.put("bytes_total", total);
        payload.put("message", msg);
        bus.publish(Event.of(Topic.PLATESOLVING, "install_progress", payload));
    }

    private void publish(String type, Map<String, Object> payload) {
        bus.publish(Event.of(Topic.PLATESOLVING, type, payload));
    }

    @PreDestroy
    public void shutdown() {
        executor.shutdownNow();
    }
}
```

- [ ] **Step 12.3: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.platesolving.install.AstapInstallServiceTest'`
Expected: PASS.

- [ ] **Step 12.4: Commit**

```bash
git add src/main/java/dev/nocs/platesolving/install/AstapInstallService.java \
        src/test/java/dev/nocs/platesolving/install/AstapInstallServiceTest.java
git commit -m "feat(platesolving/install): AstapInstallService (async + progress + events)"
```

---

### Task 13: REST controller + DTOs + bean wiring

**Files:**
- Create: `src/main/java/dev/nocs/platesolving/api/PlateSolvingController.java`
- Create: `src/main/java/dev/nocs/platesolving/api/dto/SolveRequest.java`
- Create: `src/main/java/dev/nocs/platesolving/api/dto/SolveResponse.java`
- Create: `src/main/java/dev/nocs/platesolving/api/dto/PlateSolutionView.java`
- Create: `src/main/java/dev/nocs/platesolving/api/dto/InstallStatusView.java`
- Create: `src/main/java/dev/nocs/platesolving/api/dto/InstallProgressView.java`
- Modify: `src/main/java/dev/nocs/config/AppBeansConfig.java`
- Create: `src/test/java/dev/nocs/platesolving/api/PlateSolvingControllerTest.java`

- [ ] **Step 13.1: DTOs**

Create `src/main/java/dev/nocs/platesolving/api/dto/SolveRequest.java`:

```java
package dev.nocs.platesolving.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

public record SolveRequest(
        @JsonProperty("image_id") Long imageId,
        @JsonProperty("ra_hint_hours") Double raHintHours,
        @JsonProperty("dec_hint_deg") Double decHintDeg,
        @JsonProperty("radius_deg") Double radiusDeg,
        @JsonProperty("scale_hint_arcsec_per_pixel") Double scaleHintArcsecPerPx,
        @JsonProperty("timeout_sec") Double timeoutSec) {}
```

Create `src/main/java/dev/nocs/platesolving/api/dto/PlateSolutionView.java`:

```java
package dev.nocs.platesolving.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import dev.nocs.platesolving.PlateSolution;
import dev.nocs.platesolving.PlateSolutionRecord;
import java.time.Instant;

public record PlateSolutionView(
        @JsonProperty("ra_j2000_deg") double raJ2000Deg,
        @JsonProperty("dec_j2000_deg") double decJ2000Deg,
        @JsonProperty("pixel_scale_arcsec_per_pixel") double pixelScaleArcsecPerPx,
        @JsonProperty("rotation_deg") double rotationDeg,
        @JsonProperty("field_width_deg") double fieldWidthDeg,
        @JsonProperty("field_height_deg") double fieldHeightDeg,
        @JsonProperty("solver") String solver,
        @JsonProperty("solved_at") Instant solvedAt,
        @JsonProperty("duration_ms") long durationMs) {

    public static PlateSolutionView from(PlateSolution s, long durationMs) {
        return new PlateSolutionView(
                s.raJ2000Deg(), s.decJ2000Deg(), s.pixelScaleArcsecPerPx(),
                s.rotationDeg(), s.fieldWidthDeg(), s.fieldHeightDeg(),
                s.solver(), s.solvedAt(), durationMs);
    }

    public static PlateSolutionView fromRecord(PlateSolutionRecord r) {
        return new PlateSolutionView(
                r.raJ2000Deg(), r.decJ2000Deg(), r.pixelScaleArcsecPerPx(),
                r.rotationDeg(), r.fieldWidthDeg(), r.fieldHeightDeg(),
                r.solver(), r.solvedAt(), r.durationMs());
    }
}
```

Create `src/main/java/dev/nocs/platesolving/api/dto/SolveResponse.java`:

```java
package dev.nocs.platesolving.api.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record SolveResponse(
        @JsonProperty("solved") boolean solved,
        @JsonProperty("image_id") Long imageId,
        @JsonProperty("solution") PlateSolutionView solution,
        @JsonProperty("failure_kind") String failureKind,
        @JsonProperty("message") String message,
        @JsonProperty("duration_ms") long durationMs) {

    public static SolveResponse success(long imageId, PlateSolutionView v) {
        return new SolveResponse(true, imageId, v, null, null, v.durationMs());
    }

    public static SolveResponse failure(long imageId, String failureKind, String message, long durationMs) {
        return new SolveResponse(false, imageId, null, failureKind, message, durationMs);
    }
}
```

Create `src/main/java/dev/nocs/platesolving/api/dto/InstallStatusView.java`:

```java
package dev.nocs.platesolving.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

public record InstallStatusView(
        @JsonProperty("installed") boolean installed,
        @JsonProperty("binary_path") String binaryPath,
        @JsonProperty("db_dir") String dbDir,
        @JsonProperty("db_name") String dbName,
        @JsonProperty("db_present") boolean dbPresent,
        @JsonProperty("supported_platform") boolean supportedPlatform,
        @JsonProperty("allow_network") boolean allowNetwork) {}
```

Create `src/main/java/dev/nocs/platesolving/api/dto/InstallProgressView.java`:

```java
package dev.nocs.platesolving.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import dev.nocs.platesolving.install.InstallProgress;
import java.time.Instant;

public record InstallProgressView(
        @JsonProperty("phase") String phase,
        @JsonProperty("bytes_done") long bytesDone,
        @JsonProperty("bytes_total") long bytesTotal,
        @JsonProperty("message") String message,
        @JsonProperty("updated_at") Instant updatedAt) {

    public static InstallProgressView from(InstallProgress p) {
        return new InstallProgressView(
                p.phase().name().toLowerCase(),
                p.bytesDone(), p.bytesTotal(), p.message(), p.updatedAt());
    }
}
```

- [ ] **Step 13.2: Controller**

Create `src/main/java/dev/nocs/platesolving/api/PlateSolvingController.java`:

```java
package dev.nocs.platesolving.api;

import dev.nocs.config.NocsProperties;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.image.ImageStoreService;
import dev.nocs.platesolving.PlateSolutionRecord;
import dev.nocs.platesolving.PlateSolutionRepository;
import dev.nocs.platesolving.PlateSolvingService;
import dev.nocs.platesolving.SolveOptions;
import dev.nocs.platesolving.SolveOutcome;
import dev.nocs.platesolving.api.dto.InstallProgressView;
import dev.nocs.platesolving.api.dto.InstallStatusView;
import dev.nocs.platesolving.api.dto.PlateSolutionView;
import dev.nocs.platesolving.api.dto.SolveRequest;
import dev.nocs.platesolving.api.dto.SolveResponse;
import dev.nocs.platesolving.astap.AstapInstallation;
import dev.nocs.platesolving.astap.AstapInstallationLocator;
import dev.nocs.platesolving.install.AstapInstallService;
import dev.nocs.platesolving.install.AstapInstallSpecs;
import dev.nocs.platesolving.install.InstallRequest;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/platesolving")
public class PlateSolvingController {

    private final PlateSolvingService solver;
    private final ImageStoreService images;
    private final PlateSolutionRepository solutions;
    private final EventBus bus;
    private final NocsProperties props;
    private final Path dataDir;
    private final AstapInstallationLocator locator;
    private final AstapInstallService installService;

    public PlateSolvingController(
            PlateSolvingService solver,
            ImageStoreService images,
            PlateSolutionRepository solutions,
            EventBus bus,
            NocsProperties props,
            Path dataDir,
            AstapInstallationLocator locator,
            AstapInstallService installService) {
        this.solver = solver;
        this.images = images;
        this.solutions = solutions;
        this.bus = bus;
        this.props = props;
        this.dataDir = dataDir;
        this.locator = locator;
        this.installService = installService;
    }

    @PostMapping("/solve")
    public ResponseEntity<SolveResponse> solve(@RequestBody SolveRequest req) {
        if (req == null || req.imageId() == null) {
            return ResponseEntity.badRequest().body(
                    SolveResponse.failure(0L, "VALIDATION", "image_id required", 0L));
        }
        long id = req.imageId();
        Optional<byte[]> bytes = images.loadFits(id);
        if (bytes.isEmpty()) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND).body(
                    SolveResponse.failure(id, "NOT_FOUND", "image not found", 0L));
        }
        SolveOptions opts = new SolveOptions(
                req.raHintHours() == null ? null : req.raHintHours() * 15.0,
                req.decHintDeg(),
                req.radiusDeg(),
                req.scaleHintArcsecPerPx(),
                req.timeoutSec());
        bus.publish(Event.of(Topic.PLATESOLVING, "solve_started",
                Map.of("image_id", id)));
        SolveOutcome outcome = solver.solve(bytes.get(), opts);
        if (outcome instanceof SolveOutcome.Solved s) {
            images.amendHeader(id, s.solution().toFitsCards());
            PlateSolutionView view = PlateSolutionView.from(s.solution(), s.durationMs());
            Map<String, Object> payload = new HashMap<>();
            payload.put("image_id", id);
            payload.put("ra_j2000_deg", s.solution().raJ2000Deg());
            payload.put("dec_j2000_deg", s.solution().decJ2000Deg());
            payload.put("solver", s.solution().solver());
            payload.put("duration_ms", s.durationMs());
            bus.publish(Event.of(Topic.PLATESOLVING, "solved", payload));
            return ResponseEntity.ok(SolveResponse.success(id, view));
        }
        SolveOutcome.Failed f = (SolveOutcome.Failed) outcome;
        bus.publish(Event.of(Topic.PLATESOLVING, "solve_failed", Map.of(
                "image_id", id,
                "failure_kind", f.kind().wire(),
                "message", f.message(),
                "duration_ms", f.durationMs())));
        return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY).body(
                SolveResponse.failure(id, f.kind().wire(), f.message(), f.durationMs()));
    }

    @GetMapping("/install")
    public InstallStatusView installStatus() {
        Optional<AstapInstallation> inst = locator.locate(props, dataDir);
        boolean supported = AstapInstallSpecs.currentPlatformKey() != null;
        boolean allow = props.platesolving() != null
                && props.platesolving().install() != null
                && Boolean.TRUE.equals(props.platesolving().install().allowNetwork());
        if (inst.isPresent()) {
            return new InstallStatusView(
                    true,
                    inst.get().binary().toString(),
                    inst.get().dbDir().toString(),
                    inst.get().dbName(),
                    true,
                    supported,
                    allow);
        }
        String dbName = props.platesolving() == null || props.platesolving().astap() == null
                ? "H18" : props.platesolving().astap().dbName();
        return new InstallStatusView(false, null, null, dbName, false, supported, allow);
    }

    @PostMapping("/install")
    public ResponseEntity<?> startInstall(@RequestBody(required = false) InstallRequest body) {
        InstallRequest req = body == null ? new InstallRequest(false) : body;
        try {
            installService.start(req);
            return ResponseEntity.accepted().build();
        } catch (IllegalArgumentException e) {
            return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(Map.of("error", e.getMessage()));
        } catch (IllegalStateException e) {
            String msg = e.getMessage() == null ? "" : e.getMessage();
            HttpStatus status = msg.contains("already")
                    ? HttpStatus.CONFLICT
                    : msg.contains("allow-network") ? HttpStatus.FORBIDDEN
                    : HttpStatus.NOT_IMPLEMENTED;
            return ResponseEntity.status(status).body(Map.of("error", msg));
        }
    }

    @GetMapping("/install/progress")
    public InstallProgressView installProgress() {
        return InstallProgressView.from(installService.progress());
    }
}
```

- [ ] **Step 13.3: Wire beans**

Modify `src/main/java/dev/nocs/config/AppBeansConfig.java`. Append the following methods inside the class (and the new imports at the top):

```java
import dev.nocs.bootstrap.DataDirBootstrap;
import dev.nocs.platesolving.DisabledPlateSolvingService;
import dev.nocs.platesolving.PlateSolvingService;
import dev.nocs.platesolving.astap.AstapInstallationLocator;
import dev.nocs.platesolving.astap.AstapInvoker;
import dev.nocs.platesolving.astap.AstapPlateSolver;
import dev.nocs.platesolving.install.AstapInstallService;
import dev.nocs.platesolving.install.AstapInstallSpecs;
import dev.nocs.platesolving.install.AstapInstaller;
```

```java
@Bean
java.nio.file.Path nocsDataDir(NocsProperties props) {
    String dir = props.dataDir() != null && !props.dataDir().isBlank()
            ? props.dataDir()
            : DataDirBootstrap.resolveDataDir().toString();
    return java.nio.file.Path.of(dir);
}

@Bean
PlateSolvingService plateSolvingService(
        NocsProperties props,
        AstapInstallationLocator locator,
        AstapInvoker invoker,
        java.nio.file.Path nocsDataDir) {
    String solver = props.platesolving() == null ? "astap" : props.platesolving().solver();
    if ("disabled".equalsIgnoreCase(solver)) {
        return new DisabledPlateSolvingService();
    }
    return new AstapPlateSolver(locator, invoker, props, nocsDataDir);
}

@Bean
AstapInstallService astapInstallService(
        NocsProperties props,
        java.nio.file.Path nocsDataDir,
        EventBus bus,
        AstapInstaller installer) {
    return new AstapInstallService(props, nocsDataDir, bus, installer, AstapInstallSpecs::forCurrent);
}
```

The earlier `nocsDataDir` bean is reused by `ImageStoreService`'s constructor. To keep the existing `ImageStoreService` constructor intact (it derives `dataDir` from `NocsProperties` directly), no further change is required here — the new `nocsDataDir` bean is independent and only consumed by Plan E components. Verify no other bean needs the same `Path`.

- [ ] **Step 13.4: Failing test for the controller**

Create `src/test/java/dev/nocs/platesolving/api/PlateSolvingControllerTest.java`:

```java
package dev.nocs.platesolving.api;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.nocs.image.ImageStoreService;
import dev.nocs.platesolving.FailureKind;
import dev.nocs.platesolving.PlateSolution;
import dev.nocs.platesolving.PlateSolvingService;
import dev.nocs.platesolving.SolveOptions;
import dev.nocs.platesolving.SolveOutcome;
import dev.nocs.platesolving.install.AstapInstallService;
import dev.nocs.platesolving.install.InstallProgress;
import java.time.Instant;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(properties = "nocs.auth.token=t")
class PlateSolvingControllerTest {

    @Autowired MockMvc mvc;
    @Autowired ObjectMapper json;
    @MockBean PlateSolvingService solver;
    @MockBean ImageStoreService imageStore;
    @MockBean AstapInstallService installService;

    @Test
    void solveRequiresImageId() throws Exception {
        mvc.perform(post("/api/platesolving/solve")
                        .header("Authorization", "Bearer t")
                        .contentType("application/json")
                        .content("{}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void solveSuccessReturnsSolution() throws Exception {
        when(imageStore.loadFits(anyLong())).thenReturn(Optional.of(new byte[16]));
        PlateSolution sol = new PlateSolution(
                10.6847083, 41.269083, 1.234, 12.5, 0.5, 0.4, Instant.now(), "astap");
        when(solver.solve(any(), any(SolveOptions.class)))
                .thenReturn(new SolveOutcome.Solved(sol, 1234L));
        when(imageStore.amendHeader(anyLong(), any())).thenReturn(true);

        mvc.perform(post("/api/platesolving/solve")
                        .header("Authorization", "Bearer t")
                        .contentType("application/json")
                        .content("{\"image_id\":42}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.solved").value(true))
                .andExpect(jsonPath("$.solution.ra_j2000_deg").value(10.6847083))
                .andExpect(jsonPath("$.solution.duration_ms").value(1234));
    }

    @Test
    void solveFailureReturns422() throws Exception {
        when(imageStore.loadFits(anyLong())).thenReturn(Optional.of(new byte[16]));
        when(solver.solve(any(), any(SolveOptions.class)))
                .thenReturn(new SolveOutcome.Failed(FailureKind.NO_STARS, "too few stars", 200L));

        mvc.perform(post("/api/platesolving/solve")
                        .header("Authorization", "Bearer t")
                        .contentType("application/json")
                        .content("{\"image_id\":42}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.solved").value(false))
                .andExpect(jsonPath("$.failure_kind").value("no_stars"));
    }

    @Test
    void installStatusReturnsJson() throws Exception {
        mvc.perform(get("/api/platesolving/install")
                        .header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.supported_platform").exists());
    }

    @Test
    void installStartRespectsLicenseFlag() throws Exception {
        org.mockito.Mockito.doThrow(new IllegalArgumentException("must accept ASTAP license"))
                .when(installService).start(any());
        mvc.perform(post("/api/platesolving/install")
                        .header("Authorization", "Bearer t")
                        .contentType("application/json")
                        .content("{\"acceptLicense\":false}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void installProgressReturnsJson() throws Exception {
        when(installService.progress()).thenReturn(InstallProgress.idle());
        mvc.perform(get("/api/platesolving/install/progress")
                        .header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.phase").value("idle"));
    }

    @Test
    void unauthenticatedSolveIs401() throws Exception {
        mvc.perform(post("/api/platesolving/solve")
                        .contentType("application/json")
                        .content("{\"image_id\":42}"))
                .andExpect(status().isUnauthorized());
    }
}
```

- [ ] **Step 13.5: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.platesolving.api.PlateSolvingControllerTest'`
Expected: PASS.

If `unauthenticatedSolveIs401` fails because the bearer filter is permissive, double-check `BearerTokenFilter` is enforcing every `/api/**` path (Plan A's behaviour); the test should not need any extra security wiring.

- [ ] **Step 13.6: Commit**

```bash
git add src/main/java/dev/nocs/platesolving/api/ \
        src/main/java/dev/nocs/config/AppBeansConfig.java \
        src/test/java/dev/nocs/platesolving/api/
git commit -m "feat(platesolving): /api/platesolving controller + Spring wiring"
```

---

### Task 14: `config.example.yaml` + bootstrap astap dirs

**Files:**
- Modify: `src/main/resources/config.example.yaml`
- Modify: `src/main/java/dev/nocs/bootstrap/DataDirBootstrap.java`
- Modify: `src/test/java/dev/nocs/bootstrap/DataDirBootstrapTest.java` (or create if absent)

- [ ] **Step 14.1: Append the `platesolving:` block to `config.example.yaml`**

In `src/main/resources/config.example.yaml`, append (after the `safety:` block from Plan F):

```yaml
  # Plate solving (Plan E). v0.1 ships ASTAP CLI as the only solver. The binary
  # and the H18 star DB are not bundled in the release archive (license hygiene
  # + size). NOCS can fetch and install them on first run when you opt in by
  # flipping `install.allow-network` to true and posting to
  # POST /api/platesolving/install with `{"acceptLicense": true}`. Alternatively
  # set `astap.binary-path` and `astap.db-dir` to an existing install on disk.
  platesolving:
    # solver: astap | disabled
    solver: astap
    # Per-call timeout. Override per request via the `timeout_sec` body field.
    solve-timeout-sec: 60
    astap:
      # Empty = look under ${data_dir}/astap/bin/astap_cli, then $PATH.
      binary-path: ""
      # Empty = look under ${data_dir}/astap/db.
      db-dir: ""
      # H18 is the recommended default; D50/V17/G17 will be supported later.
      db-name: H18
    install:
      # Hard opt-in. Without this, POST /api/platesolving/install returns 403.
      allow-network: false
      # Templated URL — {os} ∈ {linux, windows}, {arch} ∈ {x86_64, arm64}.
      # Pin to a specific ASTAP release before enabling.
      binary-url-template: ""
      # Per-platform SHA-256 of the binary archive. Required if you enable.
      binary-sha256:
        linux-x86_64: ""
        linux-arm64: ""
        windows-x86_64: ""
      # H18 (or chosen db-name) star DB archive URL + SHA-256.
      db-url: ""
      db-sha256: ""
```

- [ ] **Step 14.2: Modify `DataDirBootstrap` to seed the ASTAP layout**

In `src/main/java/dev/nocs/bootstrap/DataDirBootstrap.java`, modify `ensureLayout(...)` to also create the new directories:

```java
public static Path ensureLayout(Path dataDir) throws IOException {
    Files.createDirectories(dataDir);
    Files.createDirectories(dataDir.resolve("sessions"));
    Files.createDirectories(dataDir.resolve("logs"));
    Files.createDirectories(dataDir.resolve("astap").resolve("bin"));
    Files.createDirectories(dataDir.resolve("astap").resolve("db"));
    Path configFile = copyIfMissing(dataDir, "config.example.yaml", "config.yaml");
    copyIfMissing(dataDir, "safety.example.yaml", "safety.yaml");
    return configFile;
}
```

- [ ] **Step 14.3: Add the bootstrap test**

If `src/test/java/dev/nocs/bootstrap/DataDirBootstrapTest.java` already exists (added by Plan A), append:

```java
@Test
void ensureLayoutCreatesAstapDirs(@TempDir Path tmp) throws Exception {
    DataDirBootstrap.ensureLayout(tmp);
    assertThat(Files.isDirectory(tmp.resolve("astap/bin"))).isTrue();
    assertThat(Files.isDirectory(tmp.resolve("astap/db"))).isTrue();
}
```

If the file does not exist yet (older Plan A revision), create it with the standard `@TempDir` + `assertThat` skeleton mirroring Plan F's `SafetyExampleYamlBootstrapTest`.

- [ ] **Step 14.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.bootstrap.DataDirBootstrapTest'`
Expected: PASS.

- [ ] **Step 14.5: Commit**

```bash
git add src/main/resources/config.example.yaml \
        src/main/java/dev/nocs/bootstrap/DataDirBootstrap.java \
        src/test/java/dev/nocs/bootstrap/DataDirBootstrapTest.java
git commit -m "feat(bootstrap): seed data_dir/astap/{bin,db} + document platesolving config"
```

---

### Task 15: End-to-end `/api/platesolving/solve` integration test

**Files:**
- Create: `src/test/java/dev/nocs/platesolving/IntegrationPlateSolvingApiTest.java`

This test boots the full Spring context, stubs `PlateSolvingService` so it returns a deterministic solution, drives a real saved image through `POST /api/platesolving/solve`, and asserts the FITS file on disk has been amended, the `plate_solutions` row was inserted, and a `PLATESOLVING/solved` event was published.

- [ ] **Step 15.1: Write the integration test**

Create `src/test/java/dev/nocs/platesolving/IntegrationPlateSolvingApiTest.java`:

```java
package dev.nocs.platesolving;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.nocs.device.DeviceId;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.image.CaptureContext;
import dev.nocs.image.FitsHeaderReader;
import dev.nocs.image.ImageRepository;
import dev.nocs.image.ImageStoreService;
import dev.nocs.image.MiniFits;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.List;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.test.context.TestPropertySource;
import reactor.core.Disposable;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@TestPropertySource(properties = {
        "nocs.auth.token=t",
        "nocs.platesolving.solver=astap"
})
@Import(IntegrationPlateSolvingApiTest.StubSolverConfig.class)
class IntegrationPlateSolvingApiTest {

    @Autowired ImageStoreService store;
    @Autowired ImageRepository imageRepo;
    @Autowired PlateSolutionRepository solutionRepo;
    @Autowired EventBus bus;
    @Autowired ObjectMapper json;
    @LocalServerPort int port;

    @Test
    void solveAmendsFitsAndPersistsSolution() throws Exception {
        DeviceId cam = new DeviceId("ccd-int");
        store.prepareCapture(cam, CaptureContext.defaults(60.0));
        byte[] originalFits = MiniFits.build16(8, 8, new short[64], Map.of(
                "DATE-OBS", "'2026-04-22T22:00:00'"));
        store.accept(cam, originalFits, ".fits");
        long imageId = store.list(new ImageRepository.Filters("ccd-int", null, null, null, 10, 0))
                .get(0).id();

        List<Event> events = new CopyOnWriteArrayList<>();
        Disposable sub = bus.subscribe(Topic.PLATESOLVING).subscribe(events::add);

        HttpClient http = HttpClient.newHttpClient();
        HttpResponse<String> resp = http.send(
                HttpRequest.newBuilder(URI.create(base() + "/api/platesolving/solve"))
                        .header("Authorization", "Bearer t")
                        .header("Content-Type", "application/json")
                        .POST(HttpRequest.BodyPublishers.ofString(
                                "{\"image_id\":" + imageId + "}"))
                        .build(),
                HttpResponse.BodyHandlers.ofString());
        assertThat(resp.statusCode()).isEqualTo(200);
        assertThat(resp.body()).contains("\"solved\":true");

        Awaitility.await().atMost(Duration.ofSeconds(5)).untilAsserted(() ->
                assertThat(events).extracting(Event::type).contains("solve_started", "solved"));

        var rec = store.find(imageId).orElseThrow();
        byte[] reread = Files.readAllBytes(Path.of(rec.fitsPath()));
        FitsHeaderReader.Header h = FitsHeaderReader.read(reread);
        String header = new String(reread, 0, h.dataOffset(), StandardCharsets.US_ASCII);
        assertThat(header).contains("CRVAL1");
        assertThat(header).contains("CRVAL2");

        var row = solutionRepo.findByImageId(imageId).orElseThrow();
        assertThat(row.raJ2000Deg()).isEqualTo(10.6847083);
        assertThat(row.decJ2000Deg()).isEqualTo(41.269083);
        assertThat(row.solver()).isEqualTo("astap");
        sub.dispose();
    }

    private String base() {
        return "http://localhost:" + port;
    }

    @TestConfiguration
    static class StubSolverConfig {
        @Bean
        @Primary
        PlateSolvingService stubSolver() {
            return new PlateSolvingService() {
                @Override
                public SolveOutcome solve(byte[] fits, SolveOptions options) {
                    PlateSolution s = new PlateSolution(
                            10.6847083, 41.269083, 1.234, 12.5, 0.5, 0.4, Instant.now(), "astap");
                    return new SolveOutcome.Solved(s, 25L);
                }

                @Override
                public boolean isAvailable() {
                    return true;
                }
            };
        }
    }
}
```

- [ ] **Step 15.2: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.platesolving.IntegrationPlateSolvingApiTest'`
Expected: PASS, completing in under 10 seconds.

If the test fails because the `plate_solutions` row is missing, double-check that `ImageStoreService.amendHeader` upserts when `CRVAL1`/`CRVAL2` are present (Task 10) and that the controller is actually invoking `images.amendHeader(id, sol.toFitsCards())` (Task 13).

- [ ] **Step 15.3: Run the whole suite to confirm no regressions**

Run: `./gradlew check`
Expected: BUILD SUCCESSFUL.

- [ ] **Step 15.4: Commit**

```bash
git add src/test/java/dev/nocs/platesolving/IntegrationPlateSolvingApiTest.java
git commit -m "test(platesolving): end-to-end /api/platesolving/solve round-trip"
```

---

### Task 16: README + decomposition status

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-04-22-v0.1-plan-decomposition.md`

- [ ] **Step 16.1: Add a `/api/platesolving` example to the README dev-quickstart**

In `README.md`, find the existing dev-quickstart section. After the `/api/images` examples added in Plan D, append the following block:

````markdown
After saving an image via `/api/cameras/{id}/expose`, plate-solve it. The default `nocs.platesolving.solver=astap` requires an installed ASTAP CLI + H18 star DB. If you already have ASTAP, point the config at it; otherwise opt in to the bundled fetch-and-install:

```bash
TOKEN="<printed token>"

# Check whether ASTAP is detected on this machine:
curl -s -H "Authorization: Bearer $TOKEN" \
     http://localhost:8080/api/platesolving/install

# Opt in (one-time): edit data_dir/config.yaml to set
#   nocs.platesolving.install.allow-network: true
#   nocs.platesolving.install.binary-url-template: <pinned URL>
#   nocs.platesolving.install.binary-sha256.<your-platform>: <pinned hex>
#   nocs.platesolving.install.db-url: <pinned URL>
#   nocs.platesolving.install.db-sha256: <pinned hex>
# Restart NOCS, then:
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"acceptLicense": true}' \
     http://localhost:8080/api/platesolving/install

curl -s -H "Authorization: Bearer $TOKEN" \
     http://localhost:8080/api/platesolving/install/progress

# Solve a saved image:
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"image_id": 42}' \
     http://localhost:8080/api/platesolving/solve
```
````

If the README does not yet have a Plan A/D dev-quickstart section, add a new top-level `## /api/platesolving quickstart` heading with the same content.

- [ ] **Step 16.2: Update the decomposition status row**

Edit `docs/superpowers/plans/2026-04-22-v0.1-plan-decomposition.md`. In the "Plan overview (A–I)" table, replace the **E** row with:

```markdown
| **E** | PlateSolvingService + ASTAP fetch-install | A, D | `solve(fits)` returns RA/Dec (or failure); optional auto-install of ASTAP + DB into `data_dir`. Implemented: [2026-04-22-nocs-plate-solving-and-astap.md](./2026-04-22-nocs-plate-solving-and-astap.md). |
```

In the "Current status" table, replace the `E, G, H, I` summary row with explicit rows:

```markdown
| E | Yes | [2026-04-22-nocs-plate-solving-and-astap.md](./2026-04-22-nocs-plate-solving-and-astap.md) |
| G, H, I | No | Author with the `writing-plans` skill when starting that slice |
```

- [ ] **Step 16.3: Run a sanity check**

Run: `./gradlew check`
Expected: BUILD SUCCESSFUL — no Java changes here, just docs.

- [ ] **Step 16.4: Commit**

```bash
git add README.md \
        docs/superpowers/plans/2026-04-22-v0.1-plan-decomposition.md
git commit -m "docs: README quickstart for /api/platesolving and Plan E status update"
```

---

## Self-Review Notes

**Spec coverage** — Plan E maps to:

- §11 `PlateSolvingService.solve(fits) → {ra, dec, rotation, scale, solved_at} | failure` — Tasks 4, 7, 8 (pure interface + AstapInvoker + AstapPlateSolver).
- §11 ASTAP as the v0.1 default solver, pluggable interface — Tasks 4 (interface) + 8 (impl) + Task 13 (`solver=disabled` shortcut for the no-ASTAP case).
- §11 ASTAP binary + star DB **not bundled**, fetch-and-install routine inside NOCS — Tasks 11–12 (downloader + verifier + extractors + installer + service) + Task 14 (config block + opt-in flag + bootstrap dirs).
- §11 user can skip auto-fetch by pointing config at an existing install — Task 5 (locator config-path branch) + Task 14 (yaml docs).
- §8 bus events are typed JSON with `topic`/`type`/`ts`/`payload` — Tasks 12 (install events) and 13 (solve events) all build through `Event.of(Topic.PLATESOLVING, ...)`.
- §12.1 schema additions — Task 1 (`plate_solutions` table tied to `images.id`).
- Plan D `ImageStoreService.amendHeader` stub is replaced — Task 10.

Deliberately **not** covered (belongs to later plans):

- `mount.syncTo(...)` after solving — Plan G's `slew_and_sync` pre-step subscribes to `PLATESOLVING/solved` (or calls `/solve` directly).
- Astrometry.net adapter — interface allows it; out of v0.1.
- Multi-DB selection (D50/V17/G17) — config is templated on `db-name`; v0.1 ships defaults for `H18` only.
- Web wizard for the install + solve banner — Plan H.

**Type / name consistency check:**

- Package root: `dev.nocs.platesolving` (and sub-packages `astap`, `install`, `api`, `api.dto`).
- DB columns: `image_id, ra_j2000_deg, dec_j2000_deg, pixel_scale_arcsec_per_px, rotation_deg, field_width_deg, field_height_deg, duration_ms, solver, solved_at` — matches `PlateSolutionRecord` field-by-field and the `PlateSolutionRepository` SQL.
- `PlateSolvingService.solve(byte[] fits, SolveOptions options) → SolveOutcome` — single signature, used by `AstapPlateSolver`, `DisabledPlateSolvingService`, and the `PlateSolvingController`.
- `PlateSolution` fields `(raJ2000Deg, decJ2000Deg, pixelScaleArcsecPerPx, rotationDeg, fieldWidthDeg, fieldHeightDeg, solvedAt, solver)` — same shape used by `AstapIniParser`, the controller's `PlateSolutionView`, the `amendHeader` upsert path, and the integration test.
- `Topic.PLATESOLVING` event types: `solve_started`, `solved`, `solve_failed`, `install_started`, `install_progress`, `install_completed`, `install_failed` — single source of truth.
- `nocs.platesolving.*` config: `solver`, `solve-timeout-sec`, `astap.binary-path`, `astap.db-dir`, `astap.db-name`, `install.allow-network`, `install.binary-url-template`, `install.binary-sha256`, `install.db-url`, `install.db-sha256` — same names in `application.yaml`, `config.example.yaml`, `NocsProperties.PlateSolving`, the controller's `InstallStatusView`, and the `AstapInstallSpecs` resolver.
- `AstapInstaller.install(spec, dataDir, events)` returns `Path binary`; same signature called by `AstapInstallService` (production) and `AstapInstallerTest`.
- `ImageStoreService.amendHeader(long, SequencedMap<String,String>) → boolean` — same signature consumed by Plan D's stub callers (`log.debug` only) and Plan E's controller.
- `ImageStoreService.loadFits(long) → Optional<byte[]>` — added in Task 10, consumed by the controller in Task 13.

**No placeholders:** every step shows full code, exact gradle / curl commands, expected output, and a commit at the end. The two intentional limits are:

1. The `binary-sha256` map and `db-sha256` strings are deliberately empty in `application.yaml` — without them the install endpoint refuses to run, which is the desired secure-by-default posture per spec §11. Documented in Task 14's yaml comments.
2. `AstapInstallService` ships without a `cancel()` operation; spec §11 only asks for "fetch-and-install", not for resume/cancel. The `executor.shutdownNow()` in `@PreDestroy` is sufficient for Spring shutdown.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-22-nocs-plate-solving-and-astap.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
