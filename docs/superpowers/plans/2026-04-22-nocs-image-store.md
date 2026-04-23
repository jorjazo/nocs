# NOCS ImageStoreService Implementation Plan (Plan D)

> **See also:** [NOCS v0.1 plan decomposition (A–I)](./2026-04-22-v0.1-plan-decomposition.md) — full roadmap and dependencies.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the temp-dir camera sink from Plan B with a real `ImageStoreService` that, on every camera BLOB arrival, writes the FITS atomically to the canonical on-disk layout from spec §12.2, generates a stretched JPEG thumbnail, inserts a row into a new SQLite `images` table, and exposes the captures via `GET /api/images`, `GET /api/images/{id}`, `GET /api/images/{id}.fits`, `GET /api/images/{id}/thumb.jpg`, and `DELETE /api/images/{id}`. Also extends `POST /api/cameras/{id}/expose` so callers can attach optional capture metadata (`filter`, `target`, `step`, `seq`) that ends up in the canonical filename.

**Architecture:** A new `image/` package owns the lifecycle. `ImageStoreService` is the single Spring bean that implements `CameraImageSink`; `AppBeansConfig` swaps `TempDirCameraImageSink` out for it. Capture context (filter, target, step, seq, exposure seconds) is supplied per-camera via `ImageStoreService.prepareCapture(DeviceId, CaptureContext)` and consumed by the next BLOB arrival on that device — the controller calls `prepareCapture` immediately before `camera.expose(...)`. The active session id (from `SessionService.current()`) is read at store time and persisted on the row, decoupling Plan D from the sequence engine. FITS bytes are written via temp file + atomic move; thumbnail generation is best-effort and never blocks FITS persistence. The thumbnail pipeline (`FitsHeaderReader` → `FitsStretcher` → `ThumbnailGenerator`) is a pure-Java minimal implementation supporting primary HDU + `BITPIX ∈ {16, -32}` + `NAXIS=2` (covers the `indi_simulator_ccd` happy path and most real mono astro cameras); other variants still get the FITS persisted but skip the thumbnail with a warning. After saving, an `image_saved` event is published on the `CAMERA` topic with the full row payload so Plan G's sequence engine and Plan H's gallery can consume it without re-fetching.

**Tech Stack:**
- JDK 25 + Spring Boot 3.5 (from Plan A)
- `spring-boot-starter-jdbc` + Flyway + SQLite (already wired)
- Reactor `EventBus` (from Plan A) — for `image_saved` events
- `javax.imageio.ImageIO` for JPEG encoding (JDK-bundled)
- `java.nio.file.StandardCopyOption.ATOMIC_MOVE` for atomic FITS persistence
- No new runtime dependencies — keeps the §14.1 archive size envelope flat
- JUnit 5, AssertJ, Spring `MockMvc`, Awaitility (already present)

## Scope

### In scope for Plan D

1. Flyway `V3` migration: `images` table per spec §12.1.
2. `image/` package with `CaptureContext`, `PendingCaptures`, `ImageRecord`, `ImagePaths`, `ImageRepository`.
3. Minimal pure-Java FITS thumbnail pipeline: `FitsHeaderReader`, `FitsStretcher`, `ThumbnailGenerator`. Supports primary HDU, `BITPIX ∈ {16, -32}`, `NAXIS=2`, honours `BZERO`/`BSCALE`. MAD-percentile stretch (`median ± 3 × 1.4826 × MAD`), nearest-neighbour downscale to max-dim 512, JPEG quality 85.
4. `ImageStoreService` — implements `CameraImageSink`, owns `prepareCapture` / `store` / `find` / `list` / `delete`, emits `camera.image_saved` events, associates with active session via `SessionService.current()`.
5. Spring wiring: replace `TempDirCameraImageSink` bean with `ImageStoreService` in `AppBeansConfig`. Keep the `TempDirCameraImageSink` class on disk (still used in tests / fallback) but no longer wired by default.
6. REST endpoints per spec §8.2:
   - `GET /api/images` (with optional `device`, `session_id`, `target`, `filter`, `limit`, `offset` query params)
   - `GET /api/images/{id}` — JSON metadata
   - `GET /api/images/{id}.fits` — `application/fits` octet stream
   - `GET /api/images/{id}/thumb.jpg` — `image/jpeg` (or 404 if thumb generation was skipped)
   - `DELETE /api/images/{id}` — removes DB row + on-disk files
7. Extend `POST /api/cameras/{id}/expose` body to accept optional `filter`, `target`, `step`, `seq`. Controller calls `imageStoreService.prepareCapture(deviceId, ctx)` before `camera.expose(duration)`.
8. End-to-end test that drives an expose through the camera adapter's BLOB callback with a hand-built FITS payload, then asserts the file landed, the thumbnail was generated, the DB row matches, and the REST endpoints return the right bytes.
9. README dev-quickstart update with a `curl` example that downloads a FITS + thumbnail.

### Explicitly out of scope for Plan D

- Plate-solver write-back into the FITS header — Plan E will add `ImageStoreService.amendHeader(id, ...)` separately. Plan D leaves a documented stub but does not implement amendment.
- Sequence-engine-driven metadata threading — Plan G will pass richer context through `prepareCapture(...)` without changing the sink contract.
- Multi-channel / Bayer-debayered FITS, FITS cubes (`NAXIS=3`), and `BITPIX` outside `{16, -32}` — Plan D persists the FITS, skips thumbnail, logs a warning.
- Retention policies / disk-space sweeps.
- Long-term FITS index lifecycle (re-indexing after manual edits, etc.) — out of v0.1.
- ImagingService / scheduler / dithering — Plan G.
- Web UI for the gallery — Plan H.

## File Structure

All paths are relative to the repo root (`/home/jorjazo/dev/nocs/nocs`). Every file below has one responsibility; nothing should exceed ~250 lines.

**New main sources** (`src/main/java/dev/nocs/`):

- `image/CaptureContext.java` — record `{filter, target, exposureSec, step, seq}` with sanitising static factory `defaults()`.
- `image/PendingCaptures.java` — thread-safe consume-once map keyed by `DeviceId`.
- `image/ImageRecord.java` — DB row record (id, sessionId nullable, deviceId, filter, target, exposureSec, stepName, seqIndex, fitsPath, thumbPath nullable, bytes, width, height, bitpix, dateObs, createdAt).
- `image/ImagePaths.java` — canonical layout helper: `forCapture(dataDir, date, ctx) → Path`, `nextAvailable(...)` for collision avoidance, plus filter/target sanitisers.
- `image/ImageRepository.java` — JDBC `insert(ImageRecord)` (returns id), `findById`, `list(filters)`, `delete(id)`.
- `image/FitsHeaderReader.java` — parse primary-HDU header from raw bytes; expose `Header` with `bitpix`, `naxis`, `naxis1`, `naxis2`, `bzero`, `bscale`, `dateObs`, `dataOffset`.
- `image/FitsStretcher.java` — given `Header` + raw byte buffer, compute MAD-percentile stretched 8-bit `BufferedImage` downsampled to max-dim 512.
- `image/ThumbnailGenerator.java` — orchestrates reader + stretcher, encodes JPEG. Returns `Optional<byte[]>` (empty when unsupported FITS variant).
- `image/ImageStoreService.java` — `prepareCapture`, `accept` (implements `CameraImageSink`), `find`, `list`, `delete`, `amendHeader` (stub for Plan E). Emits `camera.image_saved`.
- `image/api/ImageController.java` — REST endpoints under `/api/images`.
- `image/api/dto/ImageView.java` — JSON projection.

**Modified main sources:**

- `src/main/java/dev/nocs/config/AppBeansConfig.java` — replace `TempDirCameraImageSink` bean with `ImageStoreService`.
- `src/main/java/dev/nocs/device/api/CameraController.java` — call `imageStoreService.prepareCapture(deviceId, ctx)` before `camera.expose(req.durationSeconds())`.
- `src/main/java/dev/nocs/device/api/dto/ExposeRequest.java` — add optional `filter`, `target`, `step`, `seq`.

**Resources:**

- `src/main/resources/db/migration/V3__images.sql` — new `images` table.

**New test sources** (`src/test/java/dev/nocs/`):

- `image/CaptureContextTest.java`, `PendingCapturesTest.java`.
- `image/ImagePathsTest.java`.
- `image/ImageRepositoryTest.java` — `@SpringBootTest` + `JdbcTemplate`.
- `image/FitsHeaderReaderTest.java` — uses an in-test `MiniFits.build(...)` helper to craft fixtures.
- `image/FitsStretcherTest.java`, `ThumbnailGeneratorTest.java` — same helper.
- `image/ImageStoreServiceTest.java` — `@SpringBootTest`; feeds bytes through `accept(...)`, asserts file + row + event.
- `image/api/ImageControllerTest.java` — `MockMvc`.
- `device/api/CameraControllerExposeMetadataTest.java` — expanded `MockMvc` test verifying `prepareCapture` call ordering.
- `image/IntegrationImagesApiTest.java` — `@SpringBootTest(RANDOM_PORT)`, walks the full sink → file → REST round-trip.

**New test resources:**

- `src/test/java/dev/nocs/image/MiniFits.java` — small helper class (not a test) shared across the test tree to synthesise FITS bytes from a `short[]` or `float[]` matrix. Lives under `src/test/java` because it's referenced as a Java class, not a resource.

---

## Tasks

Each task is self-contained: files listed, TDD steps with complete code, exact commands with expected output, and a commit at the end. Tasks 1–4 land schema + value objects; 5–7 build the FITS pipeline; 8–9 wire the service; 10 ships REST; 11 extends the camera expose; 12 is the end-to-end integration test; 13 updates the README + decomposition status.

---

### Task 1: V3 Flyway migration for `images` table

**Files:**
- Create: `src/main/resources/db/migration/V3__images.sql`
- Modify: `src/test/java/dev/nocs/persistence/DataSourceConfigTest.java` (add an `images` table assertion)

- [ ] **Step 1.1: Write the failing schema-presence test**

Append to `src/test/java/dev/nocs/persistence/DataSourceConfigTest.java`:

```java
@Test
void flywayCreatesImagesTable() {
    Integer count = jdbcTemplate.queryForObject(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='images'",
            Integer.class);
    assertThat(count).isEqualTo(1);
}
```

- [ ] **Step 1.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.persistence.DataSourceConfigTest.flywayCreatesImagesTable'`
Expected: FAIL with `expected: 1 but was: 0`.

- [ ] **Step 1.3: Create the migration**

Create `src/main/resources/db/migration/V3__images.sql`:

```sql
CREATE TABLE images (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    INTEGER REFERENCES sessions(id),
    device_id     TEXT    NOT NULL,
    filter        TEXT    NOT NULL DEFAULT '',
    target        TEXT    NOT NULL DEFAULT '',
    exposure_s    REAL    NOT NULL DEFAULT 0,
    step_name     TEXT    NOT NULL DEFAULT '',
    seq_index     INTEGER NOT NULL DEFAULT 0,
    fits_path     TEXT    NOT NULL,
    thumb_path    TEXT,
    bytes         INTEGER NOT NULL DEFAULT 0,
    width         INTEGER,
    height        INTEGER,
    bitpix        INTEGER,
    date_obs      TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_images_session_id ON images(session_id);
CREATE INDEX idx_images_created_at ON images(created_at);
CREATE INDEX idx_images_device_id  ON images(device_id);
CREATE INDEX idx_images_target     ON images(target);
```

- [ ] **Step 1.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.persistence.DataSourceConfigTest'`
Expected: all four `flywayCreates*` tests pass.

- [ ] **Step 1.5: Commit**

```bash
git add src/main/resources/db/migration/V3__images.sql \
        src/test/java/dev/nocs/persistence/DataSourceConfigTest.java
git commit -m "feat: V3 migration for images metadata table"
```

---

### Task 2: Domain records — `CaptureContext`, `PendingCaptures`, `ImageRecord`

**Files:**
- Create: `src/main/java/dev/nocs/image/CaptureContext.java`
- Create: `src/main/java/dev/nocs/image/PendingCaptures.java`
- Create: `src/main/java/dev/nocs/image/ImageRecord.java`
- Create: `src/test/java/dev/nocs/image/CaptureContextTest.java`
- Create: `src/test/java/dev/nocs/image/PendingCapturesTest.java`

- [ ] **Step 2.1: Failing tests for `CaptureContext`**

Create `src/test/java/dev/nocs/image/CaptureContextTest.java`:

```java
package dev.nocs.image;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class CaptureContextTest {

    @Test
    void defaultsAreSensible() {
        CaptureContext ctx = CaptureContext.defaults(120.0);
        assertThat(ctx.filter()).isEqualTo("UNK");
        assertThat(ctx.target()).isEqualTo("untargeted");
        assertThat(ctx.step()).isEmpty();
        assertThat(ctx.seq()).isZero();
        assertThat(ctx.exposureSec()).isEqualTo(120.0);
    }

    @Test
    void blanksAreCoercedToDefaults() {
        CaptureContext ctx = new CaptureContext("  ", "", 60.0, null, 0);
        assertThat(ctx.filter()).isEqualTo("UNK");
        assertThat(ctx.target()).isEqualTo("untargeted");
        assertThat(ctx.step()).isEmpty();
    }

    @Test
    void rejectsNegativeExposure() {
        assertThat(org.junit.jupiter.api.Assertions.assertThrows(
                IllegalArgumentException.class,
                () -> new CaptureContext("L", "m31", -1.0, "L_120s", 1)).getMessage())
                .contains("exposureSec");
    }
}
```

- [ ] **Step 2.2: Failing tests for `PendingCaptures`**

Create `src/test/java/dev/nocs/image/PendingCapturesTest.java`:

```java
package dev.nocs.image;

import dev.nocs.device.DeviceId;
import java.util.Optional;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class PendingCapturesTest {

    @Test
    void prepareThenConsumeYieldsContextOnce() {
        PendingCaptures pending = new PendingCaptures();
        DeviceId cam = new DeviceId("ccd-sim");
        CaptureContext ctx = new CaptureContext("L", "m31", 30.0, "L_30s", 0);

        pending.prepare(cam, ctx);

        Optional<CaptureContext> first = pending.consume(cam);
        Optional<CaptureContext> second = pending.consume(cam);

        assertThat(first).contains(ctx);
        assertThat(second).isEmpty();
    }

    @Test
    void prepareReplacesPreviousPending() {
        PendingCaptures pending = new PendingCaptures();
        DeviceId cam = new DeviceId("ccd-sim");
        pending.prepare(cam, new CaptureContext("L", "m31", 30.0, "", 0));
        pending.prepare(cam, new CaptureContext("R", "m42", 60.0, "", 0));

        assertThat(pending.consume(cam))
                .map(CaptureContext::filter)
                .contains("R");
    }
}
```

- [ ] **Step 2.3: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.image.*'`
Expected: compilation errors — none of the classes exist yet.

- [ ] **Step 2.4: Implement `CaptureContext`**

Create `src/main/java/dev/nocs/image/CaptureContext.java`:

```java
package dev.nocs.image;

public record CaptureContext(
        String filter,
        String target,
        double exposureSec,
        String step,
        int seq) {

    public CaptureContext {
        if (exposureSec < 0) {
            throw new IllegalArgumentException("exposureSec must be >= 0, got " + exposureSec);
        }
        if (filter == null || filter.isBlank()) {
            filter = "UNK";
        }
        if (target == null || target.isBlank()) {
            target = "untargeted";
        }
        if (step == null) {
            step = "";
        }
        if (seq < 0) {
            seq = 0;
        }
    }

    public static CaptureContext defaults(double exposureSec) {
        return new CaptureContext(null, null, exposureSec, null, 0);
    }
}
```

- [ ] **Step 2.5: Implement `PendingCaptures`**

Create `src/main/java/dev/nocs/image/PendingCaptures.java`:

```java
package dev.nocs.image;

import dev.nocs.device.DeviceId;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

public class PendingCaptures {

    private final Map<DeviceId, CaptureContext> pending = new ConcurrentHashMap<>();

    public void prepare(DeviceId camera, CaptureContext ctx) {
        pending.put(camera, ctx);
    }

    public Optional<CaptureContext> consume(DeviceId camera) {
        return Optional.ofNullable(pending.remove(camera));
    }
}
```

- [ ] **Step 2.6: Implement `ImageRecord`**

Create `src/main/java/dev/nocs/image/ImageRecord.java`:

```java
package dev.nocs.image;

import java.time.Instant;

public record ImageRecord(
        Long id,
        Long sessionId,
        String deviceId,
        String filter,
        String target,
        double exposureSec,
        String stepName,
        int seqIndex,
        String fitsPath,
        String thumbPath,
        long bytes,
        Integer width,
        Integer height,
        Integer bitpix,
        String dateObs,
        Instant createdAt) {

    public static ImageRecord forInsert(
            Long sessionId,
            String deviceId,
            CaptureContext ctx,
            String fitsPath,
            String thumbPath,
            long bytes,
            Integer width,
            Integer height,
            Integer bitpix,
            String dateObs) {
        return new ImageRecord(
                null, sessionId, deviceId,
                ctx.filter(), ctx.target(), ctx.exposureSec(), ctx.step(), ctx.seq(),
                fitsPath, thumbPath, bytes, width, height, bitpix, dateObs, null);
    }
}
```

- [ ] **Step 2.7: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.image.CaptureContextTest' --tests 'dev.nocs.image.PendingCapturesTest'`
Expected: all tests pass.

- [ ] **Step 2.8: Commit**

```bash
git add src/main/java/dev/nocs/image/CaptureContext.java \
        src/main/java/dev/nocs/image/PendingCaptures.java \
        src/main/java/dev/nocs/image/ImageRecord.java \
        src/test/java/dev/nocs/image/CaptureContextTest.java \
        src/test/java/dev/nocs/image/PendingCapturesTest.java
git commit -m "feat: image domain records (CaptureContext, PendingCaptures, ImageRecord)"
```

---

### Task 3: `ImagePaths` helper

**Files:**
- Create: `src/main/java/dev/nocs/image/ImagePaths.java`
- Create: `src/test/java/dev/nocs/image/ImagePathsTest.java`

- [ ] **Step 3.1: Failing test**

Create `src/test/java/dev/nocs/image/ImagePathsTest.java`:

```java
package dev.nocs.image;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.assertj.core.api.Assertions.assertThat;

class ImagePathsTest {

    private final LocalDate date = LocalDate.of(2026, 4, 22);

    @Test
    void buildsCanonicalPath(@TempDir Path tempDir) {
        CaptureContext ctx = new CaptureContext("L", "M31", 120.0, "L_120s", 1);
        Path out = ImagePaths.forCapture(tempDir, date, "ccd-sim", ctx);

        assertThat(out).isEqualTo(
                tempDir.resolve("sessions").resolve("2026-04-22").resolve("m31")
                        .resolve("L_120s_001.fits"));
    }

    @Test
    void sanitisesTargetAndFilter(@TempDir Path tempDir) {
        CaptureContext ctx = new CaptureContext("Ha 7nm", "NGC 7000", 300.0, "Ha_300s", 5);
        Path out = ImagePaths.forCapture(tempDir, date, "ccd-sim", ctx);

        assertThat(out.getParent().getFileName().toString()).isEqualTo("ngc-7000");
        assertThat(out.getFileName().toString()).isEqualTo("Ha7nm_300s_005.fits");
    }

    @Test
    void formatsExposureWithoutTrailingZeros(@TempDir Path tempDir) {
        CaptureContext ctx = new CaptureContext("L", "m31", 0.5, "L_0.5s", 1);
        Path out = ImagePaths.forCapture(tempDir, date, "ccd-sim", ctx);

        assertThat(out.getFileName().toString()).isEqualTo("L_0.5s_001.fits");
    }

    @Test
    void avoidsCollisionsByBumpingSeq(@TempDir Path tempDir) throws Exception {
        CaptureContext ctx = new CaptureContext("L", "m31", 120.0, "L_120s", 1);
        Path first = ImagePaths.forCapture(tempDir, date, "ccd-sim", ctx);
        Files.createDirectories(first.getParent());
        Files.writeString(first, "x");

        Path next = ImagePaths.nextAvailable(first);
        assertThat(next.getFileName().toString()).isEqualTo("L_120s_002.fits");
    }

    @Test
    void thumbnailSibling(@TempDir Path tempDir) {
        CaptureContext ctx = new CaptureContext("L", "m31", 120.0, "L_120s", 1);
        Path fits = ImagePaths.forCapture(tempDir, date, "ccd-sim", ctx);
        Path thumb = ImagePaths.thumbnailFor(fits);
        assertThat(thumb.getFileName().toString()).isEqualTo("L_120s_001.thumb.jpg");
    }
}
```

- [ ] **Step 3.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.image.ImagePathsTest'`
Expected: compilation errors.

- [ ] **Step 3.3: Implement `ImagePaths`**

Create `src/main/java/dev/nocs/image/ImagePaths.java`:

```java
package dev.nocs.image;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;

public final class ImagePaths {

    private static final DateTimeFormatter DATE = DateTimeFormatter.ISO_LOCAL_DATE;

    private ImagePaths() {}

    public static Path forCapture(Path dataDir, LocalDate date, String deviceId, CaptureContext ctx) {
        String filter = sanitiseFilter(ctx.filter());
        String target = sanitiseTarget(ctx.target());
        String exposure = formatExposure(ctx.exposureSec());
        int seq = ctx.seq() <= 0 ? 1 : ctx.seq();
        String filename = filter + "_" + exposure + "s_" + zeroPad(seq) + ".fits";
        return dataDir.resolve("sessions").resolve(DATE.format(date)).resolve(target).resolve(filename);
    }

    public static Path nextAvailable(Path candidate) {
        if (!Files.exists(candidate)) {
            return candidate;
        }
        Path parent = candidate.getParent();
        String name = candidate.getFileName().toString();
        // Expect <prefix>_<nnn>.fits — find the underscore before the seq.
        int dot = name.lastIndexOf('.');
        int underscore = name.lastIndexOf('_', dot);
        if (dot < 0 || underscore < 0) {
            return candidate;
        }
        String prefix = name.substring(0, underscore);
        String suffix = name.substring(dot);
        int seq;
        try {
            seq = Integer.parseInt(name.substring(underscore + 1, dot));
        } catch (NumberFormatException e) {
            return candidate;
        }
        Path next;
        do {
            seq++;
            next = parent.resolve(prefix + "_" + zeroPad(seq) + suffix);
        } while (Files.exists(next) && seq < 99_999);
        return next;
    }

    public static Path thumbnailFor(Path fits) {
        String name = fits.getFileName().toString();
        int dot = name.lastIndexOf('.');
        String stem = dot < 0 ? name : name.substring(0, dot);
        return fits.resolveSibling(stem + ".thumb.jpg");
    }

    static String sanitiseTarget(String s) {
        String trimmed = s.trim().toLowerCase();
        String slug = trimmed.replaceAll("[^a-z0-9]+", "-").replaceAll("^-|-$", "");
        return slug.isEmpty() ? "untargeted" : slug;
    }

    static String sanitiseFilter(String s) {
        String trimmed = s.trim();
        String safe = trimmed.replaceAll("[^A-Za-z0-9]", "");
        return safe.isEmpty() ? "UNK" : safe;
    }

    static String formatExposure(double seconds) {
        if (seconds == Math.floor(seconds) && !Double.isInfinite(seconds)) {
            return Long.toString((long) seconds);
        }
        String s = String.format(java.util.Locale.ROOT, "%.3f", seconds);
        // Trim trailing zeros and a dangling decimal point.
        s = s.replaceAll("0+$", "").replaceAll("\\.$", "");
        return s;
    }

    static String zeroPad(int seq) {
        if (seq < 1000) {
            return String.format(java.util.Locale.ROOT, "%03d", seq);
        }
        return Integer.toString(seq);
    }
}
```

- [ ] **Step 3.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.image.ImagePathsTest'`
Expected: all five tests pass.

- [ ] **Step 3.5: Commit**

```bash
git add src/main/java/dev/nocs/image/ImagePaths.java \
        src/test/java/dev/nocs/image/ImagePathsTest.java
git commit -m "feat: ImagePaths canonical layout helper for FITS captures"
```

---

### Task 4: `ImageRepository` JDBC

**Files:**
- Create: `src/main/java/dev/nocs/image/ImageRepository.java`
- Create: `src/test/java/dev/nocs/image/ImageRepositoryTest.java`

- [ ] **Step 4.1: Failing test**

Create `src/test/java/dev/nocs/image/ImageRepositoryTest.java`:

```java
package dev.nocs.image;

import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@TestPropertySource(properties = "nocs.auth.token=t")
class ImageRepositoryTest {

    @Autowired ImageRepository repo;

    @Test
    void insertAndFind() {
        ImageRecord rec = ImageRecord.forInsert(
                null, "ccd-sim",
                new CaptureContext("L", "m31", 120.0, "L_120s", 1),
                "/tmp/m31/L_120s_001.fits", "/tmp/m31/L_120s_001.thumb.jpg",
                4096L, 60, 60, 16, "2026-04-22T22:00:00");

        long id = repo.insert(rec);
        Optional<ImageRecord> found = repo.findById(id);

        assertThat(found).isPresent();
        assertThat(found.get().id()).isEqualTo(id);
        assertThat(found.get().filter()).isEqualTo("L");
        assertThat(found.get().bytes()).isEqualTo(4096L);
        assertThat(found.get().createdAt()).isNotNull();
    }

    @Test
    void listFiltersByDevice() {
        long aId = repo.insert(ImageRecord.forInsert(
                null, "ccd-a", new CaptureContext("L", "m31", 1, "", 1),
                "/tmp/a.fits", null, 1, 1, 1, 16, null));
        long bId = repo.insert(ImageRecord.forInsert(
                null, "ccd-b", new CaptureContext("L", "m31", 1, "", 1),
                "/tmp/b.fits", null, 1, 1, 1, 16, null));

        List<ImageRecord> onlyA = repo.list(new ImageRepository.Filters("ccd-a", null, null, null, 100, 0));
        assertThat(onlyA).extracting(ImageRecord::id).contains(aId).doesNotContain(bId);
    }

    @Test
    void deleteRemovesRow() {
        long id = repo.insert(ImageRecord.forInsert(
                null, "ccd-sim", new CaptureContext("L", "m31", 1, "", 1),
                "/tmp/x.fits", null, 1, 1, 1, 16, null));
        boolean removed = repo.delete(id);
        assertThat(removed).isTrue();
        assertThat(repo.findById(id)).isEmpty();
    }
}
```

- [ ] **Step 4.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.image.ImageRepositoryTest'`
Expected: compilation errors.

- [ ] **Step 4.3: Implement `ImageRepository`**

Create `src/main/java/dev/nocs/image/ImageRepository.java`:

```java
package dev.nocs.image;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Repository;

@Repository
public class ImageRepository {

    private final JdbcTemplate jdbc;

    public ImageRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public long insert(ImageRecord rec) {
        GeneratedKeyHolder key = new GeneratedKeyHolder();
        jdbc.update(con -> {
            var ps = con.prepareStatement(
                    "INSERT INTO images(session_id, device_id, filter, target, exposure_s, " +
                            "step_name, seq_index, fits_path, thumb_path, bytes, width, height, " +
                            "bitpix, date_obs) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    Statement.RETURN_GENERATED_KEYS);
            if (rec.sessionId() == null) {
                ps.setNull(1, java.sql.Types.INTEGER);
            } else {
                ps.setLong(1, rec.sessionId());
            }
            ps.setString(2, rec.deviceId());
            ps.setString(3, rec.filter());
            ps.setString(4, rec.target());
            ps.setDouble(5, rec.exposureSec());
            ps.setString(6, rec.stepName());
            ps.setInt(7, rec.seqIndex());
            ps.setString(8, rec.fitsPath());
            if (rec.thumbPath() == null) {
                ps.setNull(9, java.sql.Types.VARCHAR);
            } else {
                ps.setString(9, rec.thumbPath());
            }
            ps.setLong(10, rec.bytes());
            setNullableInt(ps, 11, rec.width());
            setNullableInt(ps, 12, rec.height());
            setNullableInt(ps, 13, rec.bitpix());
            if (rec.dateObs() == null) {
                ps.setNull(14, java.sql.Types.VARCHAR);
            } else {
                ps.setString(14, rec.dateObs());
            }
            return ps;
        }, key);
        return key.getKey().longValue();
    }

    public Optional<ImageRecord> findById(long id) {
        List<ImageRecord> out = jdbc.query(
                "SELECT id, session_id, device_id, filter, target, exposure_s, step_name, " +
                        "seq_index, fits_path, thumb_path, bytes, width, height, bitpix, date_obs, " +
                        "created_at FROM images WHERE id = ?",
                MAPPER, id);
        return out.isEmpty() ? Optional.empty() : Optional.of(out.get(0));
    }

    public List<ImageRecord> list(Filters filters) {
        StringBuilder sql = new StringBuilder(
                "SELECT id, session_id, device_id, filter, target, exposure_s, step_name, " +
                        "seq_index, fits_path, thumb_path, bytes, width, height, bitpix, date_obs, " +
                        "created_at FROM images WHERE 1=1");
        List<Object> args = new ArrayList<>();
        if (filters.deviceId() != null) {
            sql.append(" AND device_id = ?");
            args.add(filters.deviceId());
        }
        if (filters.sessionId() != null) {
            sql.append(" AND session_id = ?");
            args.add(filters.sessionId());
        }
        if (filters.target() != null) {
            sql.append(" AND target = ?");
            args.add(filters.target());
        }
        if (filters.filter() != null) {
            sql.append(" AND filter = ?");
            args.add(filters.filter());
        }
        sql.append(" ORDER BY id DESC LIMIT ? OFFSET ?");
        args.add(filters.limit());
        args.add(filters.offset());
        return jdbc.query(sql.toString(), MAPPER, args.toArray());
    }

    public boolean delete(long id) {
        return jdbc.update("DELETE FROM images WHERE id = ?", id) > 0;
    }

    private static void setNullableInt(java.sql.PreparedStatement ps, int idx, Integer value) throws SQLException {
        if (value == null) {
            ps.setNull(idx, java.sql.Types.INTEGER);
        } else {
            ps.setInt(idx, value);
        }
    }

    private static final RowMapper<ImageRecord> MAPPER = (ResultSet rs, int rowNum) -> {
        Long sessionId = rs.getObject("session_id") == null ? null : rs.getLong("session_id");
        Integer width = rs.getObject("width") == null ? null : rs.getInt("width");
        Integer height = rs.getObject("height") == null ? null : rs.getInt("height");
        Integer bitpix = rs.getObject("bitpix") == null ? null : rs.getInt("bitpix");
        String createdAt = rs.getString("created_at");
        Instant created = createdAt == null ? null
                : LocalDateTime.parse(createdAt.replace(' ', 'T')).toInstant(ZoneOffset.UTC);
        return new ImageRecord(
                rs.getLong("id"),
                sessionId,
                rs.getString("device_id"),
                rs.getString("filter"),
                rs.getString("target"),
                rs.getDouble("exposure_s"),
                rs.getString("step_name"),
                rs.getInt("seq_index"),
                rs.getString("fits_path"),
                rs.getString("thumb_path"),
                rs.getLong("bytes"),
                width,
                height,
                bitpix,
                rs.getString("date_obs"),
                created);
    };

    public record Filters(
            String deviceId,
            Long sessionId,
            String target,
            String filter,
            int limit,
            int offset) {

        public Filters {
            if (limit <= 0 || limit > 1000) {
                limit = 100;
            }
            if (offset < 0) {
                offset = 0;
            }
        }
    }
}
```

- [ ] **Step 4.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.image.ImageRepositoryTest'`
Expected: all three tests pass.

- [ ] **Step 4.5: Commit**

```bash
git add src/main/java/dev/nocs/image/ImageRepository.java \
        src/test/java/dev/nocs/image/ImageRepositoryTest.java
git commit -m "feat: ImageRepository for the images table"
```

---

### Task 5: `FitsHeaderReader` (and the `MiniFits` test helper)

**Files:**
- Create: `src/main/java/dev/nocs/image/FitsHeaderReader.java`
- Create: `src/test/java/dev/nocs/image/MiniFits.java`
- Create: `src/test/java/dev/nocs/image/FitsHeaderReaderTest.java`

`MiniFits` is a shared test helper for synthesising small FITS payloads. It is referenced from later tasks (FitsStretcher, ThumbnailGenerator, ImageStoreService, integration test), so it lives under `src/test/java` so all test classes can use it.

- [ ] **Step 5.1: Write the `MiniFits` helper**

Create `src/test/java/dev/nocs/image/MiniFits.java`:

```java
package dev.nocs.image;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.util.LinkedHashMap;
import java.util.Map;

/** Builds a tiny FITS file (primary HDU, BITPIX=16 or BITPIX=-32) for tests. */
public final class MiniFits {

    private MiniFits() {}

    public static byte[] build16(int width, int height, short[] pixels, Map<String, String> extraCards) {
        if (pixels.length != width * height) {
            throw new IllegalArgumentException("pixel count != width*height");
        }
        Map<String, String> cards = baseCards(16, width, height);
        cards.put("BZERO", String.valueOf(32768));
        cards.put("BSCALE", String.valueOf(1));
        if (extraCards != null) {
            cards.putAll(extraCards);
        }
        byte[] header = encodeHeader(cards);
        ByteBuffer body = ByteBuffer.allocate(round2880(pixels.length * 2));
        for (short s : pixels) {
            body.putShort(s);
        }
        return concat(header, body.array());
    }

    public static byte[] buildFloat(int width, int height, float[] pixels, Map<String, String> extraCards) {
        if (pixels.length != width * height) {
            throw new IllegalArgumentException("pixel count != width*height");
        }
        Map<String, String> cards = baseCards(-32, width, height);
        if (extraCards != null) {
            cards.putAll(extraCards);
        }
        byte[] header = encodeHeader(cards);
        ByteBuffer body = ByteBuffer.allocate(round2880(pixels.length * 4));
        for (float f : pixels) {
            body.putFloat(f);
        }
        return concat(header, body.array());
    }

    private static Map<String, String> baseCards(int bitpix, int w, int h) {
        Map<String, String> cards = new LinkedHashMap<>();
        cards.put("SIMPLE", "T");
        cards.put("BITPIX", String.valueOf(bitpix));
        cards.put("NAXIS", "2");
        cards.put("NAXIS1", String.valueOf(w));
        cards.put("NAXIS2", String.valueOf(h));
        return cards;
    }

    private static byte[] encodeHeader(Map<String, String> cards) {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        try {
            for (var entry : cards.entrySet()) {
                out.write(card(entry.getKey(), entry.getValue()));
            }
            out.write(card("END", null));
        } catch (IOException ignored) {
            // ByteArrayOutputStream never throws.
        }
        int padding = round2880(out.size()) - out.size();
        for (int i = 0; i < padding; i++) {
            out.write(' ');
        }
        return out.toByteArray();
    }

    private static byte[] card(String key, String value) {
        StringBuilder sb = new StringBuilder(80);
        sb.append(String.format("%-8s", key));
        if (value == null) {
            // END card has no '=' sign and no value.
            for (int i = sb.length(); i < 80; i++) {
                sb.append(' ');
            }
            return sb.toString().getBytes();
        }
        sb.append("= ");
        String formatted;
        if (value.startsWith("'") || value.equals("T") || value.equals("F") || isNumeric(value)) {
            formatted = String.format("%20s", value);
        } else {
            formatted = String.format("'%-18s'", value);
        }
        sb.append(formatted);
        for (int i = sb.length(); i < 80; i++) {
            sb.append(' ');
        }
        return sb.substring(0, 80).getBytes();
    }

    private static boolean isNumeric(String s) {
        try {
            Double.parseDouble(s);
            return true;
        } catch (NumberFormatException e) {
            return false;
        }
    }

    private static int round2880(int n) {
        return ((n + 2879) / 2880) * 2880;
    }

    private static byte[] concat(byte[] a, byte[] b) {
        byte[] out = new byte[a.length + b.length];
        System.arraycopy(a, 0, out, 0, a.length);
        System.arraycopy(b, 0, out, a.length, b.length);
        return out;
    }
}
```

- [ ] **Step 5.2: Failing test for `FitsHeaderReader`**

Create `src/test/java/dev/nocs/image/FitsHeaderReaderTest.java`:

```java
package dev.nocs.image;

import java.util.Map;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class FitsHeaderReaderTest {

    @Test
    void parsesBitpix16Header() {
        byte[] fits = MiniFits.build16(4, 3, new short[12], Map.of(
                "DATE-OBS", "'2026-04-22T22:00:00'"));

        FitsHeaderReader.Header h = FitsHeaderReader.read(fits);

        assertThat(h.bitpix()).isEqualTo(16);
        assertThat(h.naxis()).isEqualTo(2);
        assertThat(h.naxis1()).isEqualTo(4);
        assertThat(h.naxis2()).isEqualTo(3);
        assertThat(h.bzero()).isEqualTo(32768.0);
        assertThat(h.bscale()).isEqualTo(1.0);
        assertThat(h.dateObs()).isEqualTo("2026-04-22T22:00:00");
        assertThat(h.dataOffset()).isEqualTo(2880);
    }

    @Test
    void parsesFloatHeader() {
        byte[] fits = MiniFits.buildFloat(2, 2, new float[]{0, 0, 0, 0}, null);

        FitsHeaderReader.Header h = FitsHeaderReader.read(fits);

        assertThat(h.bitpix()).isEqualTo(-32);
        assertThat(h.bzero()).isEqualTo(0.0);
        assertThat(h.bscale()).isEqualTo(1.0);
    }

    @Test
    void rejectsTrucated() {
        org.junit.jupiter.api.Assertions.assertThrows(
                IllegalArgumentException.class,
                () -> FitsHeaderReader.read(new byte[100]));
    }
}
```

- [ ] **Step 5.3: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.image.FitsHeaderReaderTest'`
Expected: compilation errors.

- [ ] **Step 5.4: Implement `FitsHeaderReader`**

Create `src/main/java/dev/nocs/image/FitsHeaderReader.java`:

```java
package dev.nocs.image;

import java.nio.charset.StandardCharsets;

public final class FitsHeaderReader {

    private FitsHeaderReader() {}

    public record Header(
            int bitpix,
            int naxis,
            int naxis1,
            int naxis2,
            double bzero,
            double bscale,
            String dateObs,
            int dataOffset) {}

    public static Header read(byte[] bytes) {
        if (bytes == null || bytes.length < 2880) {
            throw new IllegalArgumentException("FITS payload too small: " + (bytes == null ? 0 : bytes.length));
        }
        Integer bitpix = null;
        Integer naxis = null;
        Integer naxis1 = null;
        Integer naxis2 = null;
        double bzero = 0.0;
        double bscale = 1.0;
        String dateObs = null;

        int blocks = bytes.length / 2880;
        for (int b = 0; b < blocks; b++) {
            int blockOffset = b * 2880;
            for (int c = 0; c < 36; c++) {
                int cardOffset = blockOffset + c * 80;
                String card = new String(bytes, cardOffset, 80, StandardCharsets.US_ASCII);
                String key = card.substring(0, 8).trim();
                if ("END".equals(key)) {
                    int dataOffset = (b + 1) * 2880;
                    return finish(bitpix, naxis, naxis1, naxis2, bzero, bscale, dateObs, dataOffset);
                }
                if (card.length() < 10 || card.charAt(8) != '=') {
                    continue;
                }
                String rawValue = card.substring(10).trim();
                String value = stripQuotes(splitComment(rawValue));
                switch (key) {
                    case "BITPIX" -> bitpix = parseInt(value);
                    case "NAXIS" -> naxis = parseInt(value);
                    case "NAXIS1" -> naxis1 = parseInt(value);
                    case "NAXIS2" -> naxis2 = parseInt(value);
                    case "BZERO" -> bzero = parseDouble(value, 0.0);
                    case "BSCALE" -> bscale = parseDouble(value, 1.0);
                    case "DATE-OBS" -> dateObs = value;
                    default -> {
                        // ignore other cards
                    }
                }
            }
        }
        throw new IllegalArgumentException("FITS header missing END card");
    }

    private static Header finish(Integer bitpix, Integer naxis, Integer naxis1, Integer naxis2,
                                 double bzero, double bscale, String dateObs, int dataOffset) {
        if (bitpix == null) {
            throw new IllegalArgumentException("FITS header missing BITPIX");
        }
        if (naxis == null) {
            throw new IllegalArgumentException("FITS header missing NAXIS");
        }
        return new Header(
                bitpix, naxis,
                naxis1 == null ? 0 : naxis1,
                naxis2 == null ? 0 : naxis2,
                bzero, bscale, dateObs, dataOffset);
    }

    private static String splitComment(String value) {
        // Split on a slash that's outside a quoted region.
        boolean inQuote = false;
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (c == '\'') {
                inQuote = !inQuote;
            } else if (c == '/' && !inQuote) {
                return value.substring(0, i).trim();
            }
        }
        return value.trim();
    }

    private static String stripQuotes(String s) {
        if (s.length() >= 2 && s.charAt(0) == '\'' && s.charAt(s.length() - 1) == '\'') {
            return s.substring(1, s.length() - 1).trim();
        }
        return s;
    }

    private static int parseInt(String s) {
        return Integer.parseInt(s.trim());
    }

    private static double parseDouble(String s, double fallback) {
        try {
            return Double.parseDouble(s.trim());
        } catch (NumberFormatException e) {
            return fallback;
        }
    }
}
```

- [ ] **Step 5.5: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.image.FitsHeaderReaderTest'`
Expected: all three tests pass.

- [ ] **Step 5.6: Commit**

```bash
git add src/main/java/dev/nocs/image/FitsHeaderReader.java \
        src/test/java/dev/nocs/image/MiniFits.java \
        src/test/java/dev/nocs/image/FitsHeaderReaderTest.java
git commit -m "feat: minimal FITS primary-HDU header reader + MiniFits test helper"
```

---

### Task 6: `FitsStretcher` — MAD-percentile linear stretch

**Files:**
- Create: `src/main/java/dev/nocs/image/FitsStretcher.java`
- Create: `src/test/java/dev/nocs/image/FitsStretcherTest.java`

- [ ] **Step 6.1: Failing test**

Create `src/test/java/dev/nocs/image/FitsStretcherTest.java`:

```java
package dev.nocs.image;

import java.awt.image.BufferedImage;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class FitsStretcherTest {

    @Test
    void stretchesBitpix16IntoGrayBufferedImage() {
        // 4x4 image: low half ~ 100, high half ~ 60000 (raw 16-bit unsigned semantics via BZERO=32768).
        short[] pixels = new short[16];
        for (int i = 0; i < 16; i++) {
            int raw = i < 8 ? 100 : 60000;
            pixels[i] = (short) (raw - 32768);
        }
        byte[] fits = MiniFits.build16(4, 4, pixels, null);
        FitsHeaderReader.Header h = FitsHeaderReader.read(fits);

        BufferedImage img = FitsStretcher.stretch(h, fits, 32);
        assertThat(img.getWidth()).isEqualTo(4);
        assertThat(img.getHeight()).isEqualTo(4);
        // Expect the low pixels much darker than the high pixels.
        int low = img.getRGB(0, 0) & 0xFF;
        int high = img.getRGB(3, 3) & 0xFF;
        assertThat(high).isGreaterThan(low + 50);
    }

    @Test
    void downscalesWhenLargerThanMaxDim() {
        short[] pixels = new short[64 * 64];
        byte[] fits = MiniFits.build16(64, 64, pixels, null);
        FitsHeaderReader.Header h = FitsHeaderReader.read(fits);

        BufferedImage img = FitsStretcher.stretch(h, fits, 32);
        assertThat(img.getWidth()).isLessThanOrEqualTo(32);
        assertThat(img.getHeight()).isLessThanOrEqualTo(32);
    }

    @Test
    void rejectsUnsupportedBitpix() {
        org.junit.jupiter.api.Assertions.assertThrows(
                IllegalArgumentException.class,
                () -> FitsStretcher.stretch(
                        new FitsHeaderReader.Header(8, 2, 4, 4, 0, 1, null, 2880),
                        new byte[2880 + 16],
                        32));
    }
}
```

- [ ] **Step 6.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.image.FitsStretcherTest'`
Expected: missing class.

- [ ] **Step 6.3: Implement `FitsStretcher`**

Create `src/main/java/dev/nocs/image/FitsStretcher.java`:

```java
package dev.nocs.image;

import java.awt.image.BufferedImage;
import java.nio.ByteBuffer;
import java.util.Arrays;

public final class FitsStretcher {

    private FitsStretcher() {}

    /** Reads pixels per BITPIX, applies BZERO/BSCALE, MAD-percentile stretches, downsamples to maxDim. */
    public static BufferedImage stretch(FitsHeaderReader.Header h, byte[] fits, int maxDim) {
        if (h.naxis() != 2) {
            throw new IllegalArgumentException("only NAXIS=2 supported, got " + h.naxis());
        }
        if (h.bitpix() != 16 && h.bitpix() != -32) {
            throw new IllegalArgumentException("only BITPIX in {16,-32} supported, got " + h.bitpix());
        }
        int w = h.naxis1();
        int h2 = h.naxis2();
        if (w <= 0 || h2 <= 0) {
            throw new IllegalArgumentException("invalid dimensions: " + w + "x" + h2);
        }
        float[] phys = readPhysical(h, fits, w * h2);
        float[] stats = madPercentiles(phys);
        float lo = stats[0];
        float hi = stats[1];
        if (hi <= lo) {
            hi = lo + 1f;
        }

        BufferedImage full = new BufferedImage(w, h2, BufferedImage.TYPE_BYTE_GRAY);
        for (int y = 0; y < h2; y++) {
            for (int x = 0; x < w; x++) {
                float v = phys[y * w + x];
                int g = clamp((int) (((v - lo) / (hi - lo)) * 255f));
                int rgb = (g << 16) | (g << 8) | g;
                full.setRGB(x, y, rgb);
            }
        }
        return downscale(full, maxDim);
    }

    private static float[] readPhysical(FitsHeaderReader.Header h, byte[] fits, int n) {
        ByteBuffer body = ByteBuffer.wrap(fits, h.dataOffset(), fits.length - h.dataOffset());
        float[] out = new float[n];
        if (h.bitpix() == 16) {
            for (int i = 0; i < n; i++) {
                short raw = body.getShort();
                out[i] = (float) (raw * h.bscale() + h.bzero());
            }
        } else {
            for (int i = 0; i < n; i++) {
                out[i] = (float) (body.getFloat() * h.bscale() + h.bzero());
            }
        }
        return out;
    }

    static float[] madPercentiles(float[] pixels) {
        if (pixels.length == 0) {
            return new float[]{0f, 1f};
        }
        // Sample up to 20 000 pixels for the median computation to keep this O(N log N) bounded.
        int sampleSize = Math.min(pixels.length, 20_000);
        float[] sample = new float[sampleSize];
        if (sampleSize == pixels.length) {
            System.arraycopy(pixels, 0, sample, 0, sampleSize);
        } else {
            int stride = pixels.length / sampleSize;
            for (int i = 0; i < sampleSize; i++) {
                sample[i] = pixels[i * stride];
            }
        }
        Arrays.sort(sample);
        float median = sample[sample.length / 2];
        float[] dev = new float[sample.length];
        for (int i = 0; i < sample.length; i++) {
            dev[i] = Math.abs(sample[i] - median);
        }
        Arrays.sort(dev);
        float mad = dev[dev.length / 2];
        float sigma = 1.4826f * mad;
        float lo = median - 3f * sigma;
        float hi = median + 3f * sigma;
        return new float[]{lo, hi};
    }

    private static int clamp(int v) {
        if (v < 0) return 0;
        if (v > 255) return 255;
        return v;
    }

    private static BufferedImage downscale(BufferedImage src, int maxDim) {
        int w = src.getWidth();
        int h = src.getHeight();
        if (w <= maxDim && h <= maxDim) {
            return src;
        }
        double scale = (double) maxDim / Math.max(w, h);
        int nw = Math.max(1, (int) Math.round(w * scale));
        int nh = Math.max(1, (int) Math.round(h * scale));
        BufferedImage out = new BufferedImage(nw, nh, BufferedImage.TYPE_BYTE_GRAY);
        for (int y = 0; y < nh; y++) {
            int sy = Math.min(h - 1, (int) (y / scale));
            for (int x = 0; x < nw; x++) {
                int sx = Math.min(w - 1, (int) (x / scale));
                out.setRGB(x, y, src.getRGB(sx, sy));
            }
        }
        return out;
    }
}
```

- [ ] **Step 6.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.image.FitsStretcherTest'`
Expected: all three tests pass.

- [ ] **Step 6.5: Commit**

```bash
git add src/main/java/dev/nocs/image/FitsStretcher.java \
        src/test/java/dev/nocs/image/FitsStretcherTest.java
git commit -m "feat: FITS pixel stretcher with MAD-percentile linear scaling"
```

---

### Task 7: `ThumbnailGenerator` — FITS bytes → JPEG bytes

**Files:**
- Create: `src/main/java/dev/nocs/image/ThumbnailGenerator.java`
- Create: `src/test/java/dev/nocs/image/ThumbnailGeneratorTest.java`

- [ ] **Step 7.1: Failing test**

Create `src/test/java/dev/nocs/image/ThumbnailGeneratorTest.java`:

```java
package dev.nocs.image;

import java.io.ByteArrayInputStream;
import java.util.Map;
import java.util.Optional;
import javax.imageio.ImageIO;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class ThumbnailGeneratorTest {

    @Test
    void producesJpegFromBitpix16Fits() throws Exception {
        short[] pixels = new short[64 * 48];
        for (int i = 0; i < pixels.length; i++) {
            pixels[i] = (short) ((i * 37) % 32767);
        }
        byte[] fits = MiniFits.build16(64, 48, pixels, Map.of(
                "DATE-OBS", "'2026-04-22T22:00:00'"));

        ThumbnailGenerator gen = new ThumbnailGenerator();
        Optional<byte[]> jpeg = gen.generate(fits);

        assertThat(jpeg).isPresent();
        var img = ImageIO.read(new ByteArrayInputStream(jpeg.get()));
        assertThat(img).isNotNull();
        assertThat(img.getWidth()).isLessThanOrEqualTo(512);
        assertThat(img.getHeight()).isLessThanOrEqualTo(512);
    }

    @Test
    void returnsEmptyWhenUnsupportedBitpix() {
        // Forge a FITS-like header with BITPIX=8 (unsupported); we hand-build a single 2880-byte block.
        byte[] block = new byte[2880];
        java.util.Arrays.fill(block, (byte) ' ');
        write(block, 0,    "SIMPLE  =                    T");
        write(block, 80,   "BITPIX  =                    8");
        write(block, 160,  "NAXIS   =                    2");
        write(block, 240,  "NAXIS1  =                    4");
        write(block, 320,  "NAXIS2  =                    4");
        write(block, 400,  "END");

        ThumbnailGenerator gen = new ThumbnailGenerator();
        Optional<byte[]> jpeg = gen.generate(block);

        assertThat(jpeg).isEmpty();
    }

    private static void write(byte[] target, int offset, String s) {
        byte[] bytes = s.getBytes();
        System.arraycopy(bytes, 0, target, offset, Math.min(bytes.length, 80));
    }
}
```

- [ ] **Step 7.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.image.ThumbnailGeneratorTest'`
Expected: missing class.

- [ ] **Step 7.3: Implement `ThumbnailGenerator`**

Create `src/main/java/dev/nocs/image/ThumbnailGenerator.java`:

```java
package dev.nocs.image;

import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.util.Iterator;
import java.util.Optional;
import javax.imageio.IIOImage;
import javax.imageio.ImageIO;
import javax.imageio.ImageWriteParam;
import javax.imageio.ImageWriter;
import javax.imageio.stream.ImageOutputStream;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class ThumbnailGenerator {

    private static final Logger log = LoggerFactory.getLogger(ThumbnailGenerator.class);
    private static final int MAX_DIM = 512;
    private static final float JPEG_QUALITY = 0.85f;

    public Optional<byte[]> generate(byte[] fitsBytes) {
        FitsHeaderReader.Header h;
        try {
            h = FitsHeaderReader.read(fitsBytes);
        } catch (IllegalArgumentException e) {
            log.warn("thumbnail: failed to parse FITS header ({})", e.getMessage());
            return Optional.empty();
        }
        if (h.naxis() != 2 || (h.bitpix() != 16 && h.bitpix() != -32)) {
            log.info("thumbnail: skipping unsupported FITS variant (bitpix={}, naxis={})",
                    h.bitpix(), h.naxis());
            return Optional.empty();
        }
        try {
            BufferedImage img = FitsStretcher.stretch(h, fitsBytes, MAX_DIM);
            return Optional.of(encodeJpeg(img));
        } catch (Exception e) {
            log.warn("thumbnail: failed to stretch/encode ({})", e.getMessage());
            return Optional.empty();
        }
    }

    private static byte[] encodeJpeg(BufferedImage img) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        Iterator<ImageWriter> writers = ImageIO.getImageWritersByFormatName("jpg");
        if (!writers.hasNext()) {
            throw new IOException("no JPEG writer available");
        }
        ImageWriter writer = writers.next();
        try (ImageOutputStream ios = ImageIO.createImageOutputStream(out)) {
            writer.setOutput(ios);
            ImageWriteParam param = writer.getDefaultWriteParam();
            param.setCompressionMode(ImageWriteParam.MODE_EXPLICIT);
            param.setCompressionQuality(JPEG_QUALITY);
            writer.write(null, new IIOImage(img, null, null), param);
        } finally {
            writer.dispose();
        }
        return out.toByteArray();
    }
}
```

- [ ] **Step 7.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.image.ThumbnailGeneratorTest'`
Expected: both tests pass.

- [ ] **Step 7.5: Commit**

```bash
git add src/main/java/dev/nocs/image/ThumbnailGenerator.java \
        src/test/java/dev/nocs/image/ThumbnailGeneratorTest.java
git commit -m "feat: FITS-to-JPEG ThumbnailGenerator with unsupported-variant fallback"
```

---

### Task 8: `ImageStoreService` — implements `CameraImageSink`

**Files:**
- Create: `src/main/java/dev/nocs/image/ImageStoreService.java`
- Create: `src/test/java/dev/nocs/image/ImageStoreServiceTest.java`

- [ ] **Step 8.1: Failing test**

Create `src/test/java/dev/nocs/image/ImageStoreServiceTest.java`:

```java
package dev.nocs.image;

import dev.nocs.device.DeviceId;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@TestPropertySource(properties = "nocs.auth.token=t")
class ImageStoreServiceTest {

    @Autowired ImageStoreService store;
    @Autowired ImageRepository repo;
    @Autowired EventBus bus;

    @Test
    void prepareThenStoreWritesFitsThumbAndRow() throws Exception {
        DeviceId cam = new DeviceId("ccd-sim");
        store.prepareCapture(cam, new CaptureContext("L", "M31", 30.0, "L_30s", 1));

        CopyOnWriteArrayList<Map<String, Object>> saved = new CopyOnWriteArrayList<>();
        var sub = bus.subscribe(java.util.EnumSet.of(Topic.CAMERA))
                .filter(e -> "image_saved".equals(e.type()))
                .subscribe(e -> saved.add(e.payload()));

        short[] pixels = new short[8 * 8];
        for (int i = 0; i < pixels.length; i++) {
            pixels[i] = (short) (i * 100 - 32768);
        }
        byte[] fits = MiniFits.build16(8, 8, pixels, Map.of(
                "DATE-OBS", "'2026-04-22T22:00:00'"));

        store.accept(cam, fits, ".fits");

        Awaitility.await().atMost(Duration.ofSeconds(5)).untilAsserted(() -> {
            assertThat(saved).hasSize(1);
            Long id = ((Number) saved.get(0).get("id")).longValue();
            ImageRecord rec = repo.findById(id).orElseThrow();
            assertThat(rec.filter()).isEqualTo("L");
            assertThat(rec.target()).isEqualTo("M31");
            assertThat(rec.fitsPath()).endsWith("L_30s_001.fits");
            assertThat(Path.of(rec.fitsPath())).exists();
            assertThat(rec.thumbPath()).isNotNull();
            assertThat(Path.of(rec.thumbPath())).exists();
            assertThat(Files.size(Path.of(rec.fitsPath()))).isEqualTo(fits.length);
            assertThat(rec.bitpix()).isEqualTo(16);
            assertThat(rec.width()).isEqualTo(8);
            assertThat(rec.height()).isEqualTo(8);
            assertThat(rec.dateObs()).isEqualTo("2026-04-22T22:00:00");
        });
        sub.dispose();
    }

    @Test
    void usesDefaultsWhenNoCapturePrepared() throws Exception {
        DeviceId cam = new DeviceId("ccd-other");
        byte[] fits = MiniFits.build16(4, 4, new short[16], null);

        store.accept(cam, fits, ".fits");

        Awaitility.await().atMost(Duration.ofSeconds(2)).untilAsserted(() -> {
            var rows = repo.list(new ImageRepository.Filters("ccd-other", null, null, null, 10, 0));
            assertThat(rows).isNotEmpty();
            ImageRecord rec = rows.get(0);
            assertThat(rec.filter()).isEqualTo("UNK");
            assertThat(rec.target()).isEqualTo("untargeted");
            assertThat(Path.of(rec.fitsPath())).exists();
        });
    }
}
```

- [ ] **Step 8.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.image.ImageStoreServiceTest'`
Expected: missing class / not a Spring bean yet.

- [ ] **Step 8.3: Implement `ImageStoreService`**

Create `src/main/java/dev/nocs/image/ImageStoreService.java`:

```java
package dev.nocs.image;

import dev.nocs.config.NocsProperties;
import dev.nocs.device.CameraImageSink;
import dev.nocs.device.DeviceId;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.session.Session;
import dev.nocs.session.SessionService;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
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
public class ImageStoreService implements CameraImageSink {

    private static final Logger log = LoggerFactory.getLogger(ImageStoreService.class);

    private final ImageRepository repo;
    private final EventBus bus;
    private final ThumbnailGenerator thumbnails;
    private final PendingCaptures pending = new PendingCaptures();
    private final Path dataDir;
    private final ObjectProvider<SessionService> sessionService;

    public ImageStoreService(
            ImageRepository repo,
            EventBus bus,
            ThumbnailGenerator thumbnails,
            NocsProperties props,
            ObjectProvider<SessionService> sessionService) {
        this.repo = repo;
        this.bus = bus;
        this.thumbnails = thumbnails;
        String dir = props.dataDir() != null ? props.dataDir() : System.getProperty("java.io.tmpdir");
        this.dataDir = Path.of(dir);
        this.sessionService = sessionService;
    }

    public void prepareCapture(DeviceId camera, CaptureContext ctx) {
        pending.prepare(camera, ctx);
    }

    @Override
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

    /**
     * Stub for Plan E: plate solver will amend the saved FITS header (RA/Dec/scale/rotation) and
     * re-derive width/height/dateObs in the row. v0.1 (Plan D) does not implement amendment.
     */
    public void amendHeader(long id, Map<String, String> additionalCards) {
        log.debug("amendHeader stub called for id={} (cards={}), no-op in Plan D", id, additionalCards);
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

- [ ] **Step 8.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.image.ImageStoreServiceTest'`
Expected: both tests pass. If you get `No qualifying bean of type 'CameraImageSink'` because Plan B's bean conflicts, that's fixed in Task 9 — for now this test runs because `ImageStoreService` is `@Service`-annotated and gets injected directly.

If the test fails because Plan B's `TempDirCameraImageSink` bean and `ImageStoreService` both implement `CameraImageSink` and Spring can't decide which to inject into `DeviceService`: temporarily annotate the new bean with `@Primary` (we'll fix it cleanly in Task 9 by removing the old bean).

- [ ] **Step 8.5: Commit**

```bash
git add src/main/java/dev/nocs/image/ImageStoreService.java \
        src/test/java/dev/nocs/image/ImageStoreServiceTest.java
git commit -m "feat: ImageStoreService persists FITS + thumbnail + DB row + image_saved event"
```

---

### Task 9: Wire `ImageStoreService` as the single `CameraImageSink` bean

**Files:**
- Modify: `src/main/java/dev/nocs/config/AppBeansConfig.java`

- [ ] **Step 9.1: Replace the sink bean**

Edit `src/main/java/dev/nocs/config/AppBeansConfig.java`:

Remove the existing `cameraImageSink` `@Bean` method. Replace it with one that returns the `ImageStoreService` so Plan B's `DeviceService` keeps getting a `CameraImageSink`:

```java
@Bean
CameraImageSink cameraImageSink(ImageStoreService imageStore) {
    return imageStore;
}
```

Remove the now-unused imports for `TempDirCameraImageSink` and `Path`. Keep the `TempDirCameraImageSink` source file on disk — it's still referenced by `TempDirCameraImageSinkTest` and remains a usable fallback.

- [ ] **Step 9.2: If `@Primary` was added in Task 8, remove it**

Edit `src/main/java/dev/nocs/image/ImageStoreService.java` and remove `@org.springframework.context.annotation.Primary` if you added it as a temporary measure in Task 8.4. There is now only one `CameraImageSink` bean.

- [ ] **Step 9.3: Run the full test suite**

Run: `./gradlew test`
Expected: all existing tests pass; the previously-failing `TempDirCameraImageSinkTest` (a unit test that constructs the class directly without DI) still passes; `ImageStoreServiceTest` still passes.

- [ ] **Step 9.4: Commit**

```bash
git add src/main/java/dev/nocs/config/AppBeansConfig.java \
        src/main/java/dev/nocs/image/ImageStoreService.java
git commit -m "feat: wire ImageStoreService as the CameraImageSink bean"
```

---

### Task 10: `/api/images` REST endpoints

**Files:**
- Create: `src/main/java/dev/nocs/image/api/ImageController.java`
- Create: `src/main/java/dev/nocs/image/api/dto/ImageView.java`
- Create: `src/test/java/dev/nocs/image/api/ImageControllerTest.java`

- [ ] **Step 10.1: Failing controller test**

Create `src/test/java/dev/nocs/image/api/ImageControllerTest.java`:

```java
package dev.nocs.image.api;

import dev.nocs.device.DeviceId;
import dev.nocs.image.CaptureContext;
import dev.nocs.image.ImageStoreService;
import dev.nocs.image.MiniFits;
import java.time.Duration;
import java.util.Map;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(properties = "nocs.auth.token=t")
class ImageControllerTest {

    @Autowired MockMvc mvc;
    @Autowired ImageStoreService store;

    @Test
    void listGetFitsThumbAndDelete() throws Exception {
        DeviceId cam = new DeviceId("ccd-rest");
        store.prepareCapture(cam, new CaptureContext("R", "M42", 30.0, "R_30s", 1));
        byte[] fits = MiniFits.build16(8, 8, new short[64], Map.of(
                "DATE-OBS", "'2026-04-22T22:30:00'"));
        store.accept(cam, fits, ".fits");

        Awaitility.await().atMost(Duration.ofSeconds(3))
                .until(() -> !store.list(new dev.nocs.image.ImageRepository.Filters(
                        cam.value(), null, null, null, 10, 0)).isEmpty());

        long id = store.list(new dev.nocs.image.ImageRepository.Filters(
                cam.value(), null, null, null, 10, 0)).get(0).id();

        // List
        mvc.perform(get("/api/images?device=ccd-rest").header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$").isArray())
                .andExpect(jsonPath("$[0].id").value((int) id));

        // Get JSON
        mvc.perform(get("/api/images/" + id).header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.filter").value("R"))
                .andExpect(jsonPath("$.target").value("M42"));

        // FITS download
        MvcResult fitsResult = mvc.perform(get("/api/images/" + id + ".fits")
                        .header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(header().string("Content-Type", "application/fits"))
                .andReturn();
        assertThat(fitsResult.getResponse().getContentAsByteArray()).isEqualTo(fits);

        // Thumbnail
        mvc.perform(get("/api/images/" + id + "/thumb.jpg")
                        .header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(header().string("Content-Type", "image/jpeg"));

        // Delete
        mvc.perform(delete("/api/images/" + id).header("Authorization", "Bearer t"))
                .andExpect(status().isNoContent());
        mvc.perform(get("/api/images/" + id).header("Authorization", "Bearer t"))
                .andExpect(status().isNotFound());
    }

    @Test
    void unauthorizedRejected() throws Exception {
        mvc.perform(get("/api/images")).andExpect(status().isUnauthorized());
    }

    @Test
    void unknownIdReturns404() throws Exception {
        mvc.perform(get("/api/images/99999999").header("Authorization", "Bearer t"))
                .andExpect(status().isNotFound());
        mvc.perform(get("/api/images/99999999.fits").header("Authorization", "Bearer t"))
                .andExpect(status().isNotFound());
    }

    @Test
    void thumbAbsentWhenSkipped() throws Exception {
        DeviceId cam = new DeviceId("ccd-nothumb");
        // Build an unsupported-variant FITS (BITPIX=8) — header reader accepts it but stretcher won't.
        byte[] block = new byte[2880];
        java.util.Arrays.fill(block, (byte) ' ');
        write(block, 0, "SIMPLE  =                    T");
        write(block, 80, "BITPIX  =                    8");
        write(block, 160, "NAXIS   =                    2");
        write(block, 240, "NAXIS1  =                    4");
        write(block, 320, "NAXIS2  =                    4");
        write(block, 400, "END");
        store.accept(cam, block, ".fits");

        Awaitility.await().atMost(Duration.ofSeconds(2))
                .until(() -> !store.list(new dev.nocs.image.ImageRepository.Filters(
                        cam.value(), null, null, null, 10, 0)).isEmpty());
        long id = store.list(new dev.nocs.image.ImageRepository.Filters(
                cam.value(), null, null, null, 10, 0)).get(0).id();

        mvc.perform(get("/api/images/" + id + "/thumb.jpg")
                        .header("Authorization", "Bearer t"))
                .andExpect(status().isNotFound());

        // Cleanup
        mvc.perform(delete("/api/images/" + id).header("Authorization", "Bearer t"))
                .andExpect(status().isNoContent());
    }

    private static void write(byte[] target, int offset, String s) {
        byte[] bytes = s.getBytes();
        System.arraycopy(bytes, 0, target, offset, Math.min(bytes.length, 80));
    }
}
```

- [ ] **Step 10.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.image.api.ImageControllerTest'`
Expected: 404 / no controller mapping yet.

- [ ] **Step 10.3: Implement `ImageView`**

Create `src/main/java/dev/nocs/image/api/dto/ImageView.java`:

```java
package dev.nocs.image.api.dto;

import dev.nocs.image.ImageRecord;
import java.time.Instant;

public record ImageView(
        long id,
        Long sessionId,
        String device,
        String filter,
        String target,
        double exposureSec,
        String step,
        int seq,
        String fitsPath,
        String thumbPath,
        long bytes,
        Integer width,
        Integer height,
        Integer bitpix,
        String dateObs,
        Instant createdAt) {

    public static ImageView from(ImageRecord r) {
        return new ImageView(
                r.id(), r.sessionId(), r.deviceId(),
                r.filter(), r.target(), r.exposureSec(), r.stepName(), r.seqIndex(),
                r.fitsPath(), r.thumbPath(),
                r.bytes(), r.width(), r.height(), r.bitpix(), r.dateObs(),
                r.createdAt());
    }
}
```

- [ ] **Step 10.4: Implement `ImageController`**

Create `src/main/java/dev/nocs/image/api/ImageController.java`:

```java
package dev.nocs.image.api;

import dev.nocs.image.ImageRecord;
import dev.nocs.image.ImageRepository;
import dev.nocs.image.ImageStoreService;
import dev.nocs.image.api.dto.ImageView;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Optional;
import org.springframework.core.io.FileSystemResource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/images")
public class ImageController {

    public static final MediaType FITS_TYPE = MediaType.parseMediaType("application/fits");

    private final ImageStoreService store;

    public ImageController(ImageStoreService store) {
        this.store = store;
    }

    @GetMapping
    public List<ImageView> list(
            @RequestParam(value = "device", required = false) String device,
            @RequestParam(value = "session_id", required = false) Long sessionId,
            @RequestParam(value = "target", required = false) String target,
            @RequestParam(value = "filter", required = false) String filter,
            @RequestParam(value = "limit", defaultValue = "100") int limit,
            @RequestParam(value = "offset", defaultValue = "0") int offset) {
        return store.list(new ImageRepository.Filters(device, sessionId, target, filter, limit, offset))
                .stream().map(ImageView::from).toList();
    }

    @GetMapping("/{id}")
    public ResponseEntity<ImageView> get(@PathVariable long id) {
        return store.find(id)
                .map(r -> ResponseEntity.ok(ImageView.from(r)))
                .orElse(ResponseEntity.notFound().build());
    }

    @GetMapping("/{id}.fits")
    public ResponseEntity<?> downloadFits(@PathVariable long id) throws IOException {
        Optional<ImageRecord> rec = store.find(id);
        if (rec.isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        Path path = Path.of(rec.get().fitsPath());
        if (!Files.exists(path)) {
            return ResponseEntity.notFound().build();
        }
        HttpHeaders headers = new HttpHeaders();
        headers.set(HttpHeaders.CONTENT_DISPOSITION,
                "attachment; filename=\"" + path.getFileName().toString() + "\"");
        return ResponseEntity.ok()
                .headers(headers)
                .contentType(FITS_TYPE)
                .contentLength(Files.size(path))
                .body(new FileSystemResource(path));
    }

    @GetMapping("/{id}/thumb.jpg")
    public ResponseEntity<?> downloadThumb(@PathVariable long id) throws IOException {
        Optional<ImageRecord> rec = store.find(id);
        if (rec.isEmpty() || rec.get().thumbPath() == null) {
            return ResponseEntity.notFound().build();
        }
        Path path = Path.of(rec.get().thumbPath());
        if (!Files.exists(path)) {
            return ResponseEntity.notFound().build();
        }
        return ResponseEntity.ok()
                .contentType(MediaType.IMAGE_JPEG)
                .contentLength(Files.size(path))
                .body(new FileSystemResource(path));
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<Void> delete(@PathVariable long id) {
        boolean removed = store.delete(id);
        return removed ? ResponseEntity.noContent().build() : ResponseEntity.notFound().build();
    }
}
```

- [ ] **Step 10.5: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.image.api.ImageControllerTest'`
Expected: all four tests pass.

- [ ] **Step 10.6: Commit**

```bash
git add src/main/java/dev/nocs/image/api/ \
        src/test/java/dev/nocs/image/api/ImageControllerTest.java
git commit -m "feat: REST endpoints for /api/images list, get, fits, thumb, delete"
```

---

### Task 11: Extend `POST /api/cameras/{id}/expose` with capture metadata

**Files:**
- Modify: `src/main/java/dev/nocs/device/api/dto/ExposeRequest.java`
- Modify: `src/main/java/dev/nocs/device/api/CameraController.java`
- Create: `src/test/java/dev/nocs/device/api/CameraControllerExposeMetadataTest.java`

- [ ] **Step 11.1: Failing test**

Create `src/test/java/dev/nocs/device/api/CameraControllerExposeMetadataTest.java`:

```java
package dev.nocs.device.api;

import dev.nocs.device.Camera;
import dev.nocs.device.CameraState;
import dev.nocs.device.Device;
import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceKind;
import dev.nocs.device.DeviceRegistry;
import dev.nocs.device.DeviceService;
import dev.nocs.image.CaptureContext;
import dev.nocs.image.ImageStoreService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.boot.test.mock.mockito.SpyBean;
import org.springframework.http.MediaType;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(properties = "nocs.auth.token=t")
class CameraControllerExposeMetadataTest {

    @Autowired MockMvc mvc;
    @MockBean DeviceService deviceService;
    @SpyBean ImageStoreService imageStore;

    private Camera camera;

    @BeforeEach
    void setUp() {
        DeviceRegistry registry = new DeviceRegistry();
        camera = new FakeCamera(new DeviceId("ccd-x"));
        registry.add(camera);
        when(deviceService.registry()).thenReturn(registry);
    }

    @Test
    void exposeWithMetadataPreparesCaptureFirst() throws Exception {
        mvc.perform(post("/api/cameras/ccd-x/expose")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"durationSeconds\":120,\"filter\":\"L\",\"target\":\"M31\",\"step\":\"L_120s\",\"seq\":3}"))
                .andExpect(status().isOk());

        ArgumentCaptor<CaptureContext> ctxCap = ArgumentCaptor.forClass(CaptureContext.class);
        var inOrder = inOrder(imageStore, (Object) camera);
        inOrder.verify(imageStore).prepareCapture(eq(new DeviceId("ccd-x")), ctxCap.capture());

        CaptureContext ctx = ctxCap.getValue();
        assertThat(ctx.filter()).isEqualTo("L");
        assertThat(ctx.target()).isEqualTo("M31");
        assertThat(ctx.exposureSec()).isEqualTo(120.0);
        assertThat(ctx.step()).isEqualTo("L_120s");
        assertThat(ctx.seq()).isEqualTo(3);
        assertThat(((FakeCamera) camera).exposeCalls).isEqualTo(1);
    }

    @Test
    void exposeWithoutMetadataStillPreparesWithDefaults() throws Exception {
        mvc.perform(post("/api/cameras/ccd-x/expose")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"durationSeconds\":15}"))
                .andExpect(status().isOk());

        ArgumentCaptor<CaptureContext> ctxCap = ArgumentCaptor.forClass(CaptureContext.class);
        verify(imageStore).prepareCapture(any(), ctxCap.capture());
        assertThat(ctxCap.getValue().filter()).isEqualTo("UNK");
        assertThat(ctxCap.getValue().target()).isEqualTo("untargeted");
        assertThat(ctxCap.getValue().exposureSec()).isEqualTo(15.0);
    }

    private static final class FakeCamera implements Camera {
        private final DeviceId id;
        int exposeCalls = 0;

        FakeCamera(DeviceId id) {
            this.id = id;
        }

        @Override public DeviceId id() { return id; }
        @Override public String indiName() { return id.value(); }
        @Override public DeviceKind kind() { return DeviceKind.CAMERA; }
        @Override public boolean isConnected() { return true; }
        @Override public void connect() {}
        @Override public void disconnect() {}
        @Override public CameraState state() { return CameraState.IDLE; }
        @Override public void cool(double setpointCelsius) {}
        @Override public void expose(double durationSeconds) { exposeCalls++; }
        @Override public void abortExposure() {}
        @Override public Double currentTemperatureCelsius() { return null; }
    }
}
```

- [ ] **Step 11.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.device.api.CameraControllerExposeMetadataTest'`
Expected: failures — `ExposeRequest` doesn't have the new fields and `CameraController` doesn't call `prepareCapture`.

- [ ] **Step 11.3: Extend `ExposeRequest`**

Replace `src/main/java/dev/nocs/device/api/dto/ExposeRequest.java`:

```java
package dev.nocs.device.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

public record ExposeRequest(
        double durationSeconds,
        @JsonProperty("filter") String filter,
        @JsonProperty("target") String target,
        @JsonProperty("step") String step,
        @JsonProperty("seq") Integer seq) {

    public ExposeRequest(double durationSeconds) {
        this(durationSeconds, null, null, null, null);
    }
}
```

- [ ] **Step 11.4: Wire `prepareCapture` into `CameraController`**

Replace `src/main/java/dev/nocs/device/api/CameraController.java`:

```java
package dev.nocs.device.api;

import dev.nocs.device.Camera;
import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceService;
import dev.nocs.device.api.dto.CoolRequest;
import dev.nocs.device.api.dto.ExposeRequest;
import dev.nocs.image.CaptureContext;
import dev.nocs.image.ImageStoreService;
import java.util.NoSuchElementException;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/cameras/{id}")
public class CameraController {

    private final DeviceService service;
    private final ImageStoreService imageStore;

    public CameraController(DeviceService service, ImageStoreService imageStore) {
        this.service = service;
        this.imageStore = imageStore;
    }

    @PostMapping("/expose")
    public void expose(@PathVariable String id, @RequestBody ExposeRequest req) {
        DeviceId deviceId = new DeviceId(id);
        CaptureContext ctx = new CaptureContext(
                req.filter(),
                req.target(),
                req.durationSeconds(),
                req.step(),
                req.seq() == null ? 0 : req.seq());
        imageStore.prepareCapture(deviceId, ctx);
        camera(id).expose(req.durationSeconds());
    }

    @PostMapping("/cool")
    public void cool(@PathVariable String id, @RequestBody CoolRequest req) {
        camera(id).cool(req.setpointCelsius());
    }

    private Camera camera(String id) {
        return service.registry()
                .camera(new DeviceId(id))
                .orElseThrow(() -> new NoSuchElementException("no camera: " + id));
    }
}
```

- [ ] **Step 11.5: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.device.api.CameraControllerExposeMetadataTest'`
Expected: both tests pass.

If pre-existing camera-controller tests in Plan B's tree previously didn't expect a `prepareCapture` call, they should still pass — they construct `ExposeRequest` via the convenience single-arg ctor and the spy isn't enabled there.

Run: `./gradlew test`
Expected: full suite green.

- [ ] **Step 11.6: Commit**

```bash
git add src/main/java/dev/nocs/device/api/dto/ExposeRequest.java \
        src/main/java/dev/nocs/device/api/CameraController.java \
        src/test/java/dev/nocs/device/api/CameraControllerExposeMetadataTest.java
git commit -m "feat: expose endpoint accepts filter/target/step/seq, calls prepareCapture"
```

---

### Task 12: End-to-end integration test

**Files:**
- Create: `src/test/java/dev/nocs/image/IntegrationImagesApiTest.java`

This test exercises the full chain: `POST /api/cameras/{id}/expose` → `prepareCapture` → adapter `onBlob` callback (we invoke it directly via a stand-in `Camera` bean, not via a real `indiserver`, to keep this test fast and Linux-bin-free) → `ImageStoreService.accept` → file on disk + DB row + REST endpoints return the right bytes.

- [ ] **Step 12.1: Write the test**

Create `src/test/java/dev/nocs/image/IntegrationImagesApiTest.java`:

```java
package dev.nocs.image;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import dev.nocs.device.Camera;
import dev.nocs.device.CameraImageSink;
import dev.nocs.device.CameraState;
import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceKind;
import dev.nocs.device.DeviceRegistry;
import dev.nocs.device.DeviceService;
import dev.nocs.session.SessionService;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@TestPropertySource(properties = "nocs.auth.token=t")
class IntegrationImagesApiTest {

    @Autowired CameraImageSink sink;
    @Autowired SessionService sessions;
    @Autowired ObjectMapper json;
    @LocalServerPort int port;
    @MockBean DeviceService deviceService;

    @Test
    void exposeThenDownloadRoundTrip() throws Exception {
        DeviceId cam = new DeviceId("ccd-int");
        DeviceRegistry registry = new DeviceRegistry();
        registry.add(new StubCamera(cam));
        when(deviceService.registry()).thenReturn(registry);

        sessions.open("integration");

        HttpClient http = HttpClient.newHttpClient();

        // 1) POST /api/cameras/ccd-int/expose with metadata
        ObjectNode body = json.createObjectNode()
                .put("durationSeconds", 5.0)
                .put("filter", "L")
                .put("target", "M31")
                .put("step", "L_5s")
                .put("seq", 1);
        HttpResponse<String> exposeResp = http.send(
                HttpRequest.newBuilder(URI.create(base() + "/api/cameras/ccd-int/expose"))
                        .header("Authorization", "Bearer t")
                        .header("Content-Type", "application/json")
                        .POST(HttpRequest.BodyPublishers.ofString(body.toString()))
                        .build(),
                HttpResponse.BodyHandlers.ofString());
        assertThat(exposeResp.statusCode()).isEqualTo(200);

        // 2) Adapter would call sink.accept(...) when the BLOB arrives — simulate that here.
        short[] pixels = new short[16 * 16];
        for (int i = 0; i < pixels.length; i++) {
            pixels[i] = (short) (i * 50 - 32768);
        }
        byte[] fits = MiniFits.build16(16, 16, pixels, Map.of(
                "DATE-OBS", "'2026-04-22T22:45:00'"));
        sink.accept(cam, fits, ".fits");

        // 3) GET /api/images?device=ccd-int — wait for the row
        Awaitility.await().atMost(Duration.ofSeconds(5)).untilAsserted(() -> {
            HttpResponse<String> listResp = http.send(
                    HttpRequest.newBuilder(URI.create(base() + "/api/images?device=ccd-int"))
                            .header("Authorization", "Bearer t").GET().build(),
                    HttpResponse.BodyHandlers.ofString());
            assertThat(listResp.statusCode()).isEqualTo(200);
            assertThat(listResp.body()).contains("\"target\":\"M31\"");
        });

        long id = json.readTree(http.send(
                HttpRequest.newBuilder(URI.create(base() + "/api/images?device=ccd-int"))
                        .header("Authorization", "Bearer t").GET().build(),
                HttpResponse.BodyHandlers.ofString()).body()).get(0).get("id").asLong();

        // 4) GET FITS
        HttpResponse<byte[]> fitsResp = http.send(
                HttpRequest.newBuilder(URI.create(base() + "/api/images/" + id + ".fits"))
                        .header("Authorization", "Bearer t").GET().build(),
                HttpResponse.BodyHandlers.ofByteArray());
        assertThat(fitsResp.statusCode()).isEqualTo(200);
        assertThat(fitsResp.body()).isEqualTo(fits);

        // 5) GET thumb
        HttpResponse<byte[]> thumbResp = http.send(
                HttpRequest.newBuilder(URI.create(base() + "/api/images/" + id + "/thumb.jpg"))
                        .header("Authorization", "Bearer t").GET().build(),
                HttpResponse.BodyHandlers.ofByteArray());
        assertThat(thumbResp.statusCode()).isEqualTo(200);
        assertThat(thumbResp.body().length).isGreaterThan(100);

        // 6) DELETE
        HttpResponse<String> delResp = http.send(
                HttpRequest.newBuilder(URI.create(base() + "/api/images/" + id))
                        .header("Authorization", "Bearer t")
                        .DELETE().build(),
                HttpResponse.BodyHandlers.ofString());
        assertThat(delResp.statusCode()).isEqualTo(204);

        sessions.close();
    }

    private String base() {
        return "http://localhost:" + port;
    }

    private static final class StubCamera implements Camera {
        private final DeviceId id;
        StubCamera(DeviceId id) { this.id = id; }
        @Override public DeviceId id() { return id; }
        @Override public String indiName() { return id.value(); }
        @Override public DeviceKind kind() { return DeviceKind.CAMERA; }
        @Override public boolean isConnected() { return true; }
        @Override public void connect() {}
        @Override public void disconnect() {}
        @Override public CameraState state() { return CameraState.IDLE; }
        @Override public void cool(double setpointCelsius) {}
        @Override public void expose(double durationSeconds) {}
        @Override public void abortExposure() {}
        @Override public Double currentTemperatureCelsius() { return null; }
    }
}
```

- [ ] **Step 12.2: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.image.IntegrationImagesApiTest'`
Expected: PASS. The test should complete in under 10 s.

If the FITS bytes returned by `GET /api/images/{id}.fits` don't equal the original (e.g. trailing-byte mismatch), check the atomic-move path in `ImageStoreService.saveAndPublish` and confirm `Files.write` is writing the full byte array verbatim. The test compares the entire response body to the bytes the test handed to `sink.accept`.

- [ ] **Step 12.3: Run the whole suite to confirm no regressions**

Run: `./gradlew check`
Expected: BUILD SUCCESSFUL.

- [ ] **Step 12.4: Commit**

```bash
git add src/test/java/dev/nocs/image/IntegrationImagesApiTest.java
git commit -m "test: end-to-end /api/images round-trip through ImageStoreService"
```

---

### Task 13: README update + decomposition status row

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-04-22-v0.1-plan-decomposition.md`

- [ ] **Step 13.1: Add a `/api/images` example to the README dev-quickstart**

In `README.md`, find the existing dev-quickstart section. After the `curl … /api/config` example (added in Plan A) and the `/api/targets/search` example (added in Plan C), append the following block:

````markdown
After triggering an exposure on a connected camera (real driver or `indi_simulator_ccd`):

```bash
TOKEN="<printed token>"
curl -s -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"durationSeconds":30,"filter":"L","target":"M31","step":"L_30s","seq":1}' \
     http://localhost:8080/api/cameras/<camera-id>/expose

curl -s -H "Authorization: Bearer $TOKEN" \
     "http://localhost:8080/api/images?device=<camera-id>"

# The response includes the new image id; download the FITS and the thumbnail:
ID=<id-from-list>
curl -s -H "Authorization: Bearer $TOKEN" \
     -o capture.fits "http://localhost:8080/api/images/$ID.fits"
curl -s -H "Authorization: Bearer $TOKEN" \
     -o capture.thumb.jpg "http://localhost:8080/api/images/$ID/thumb.jpg"
```
````

If the README does not yet have a Plan A/C dev-quickstart section (i.e. you're working in a different branch), add a new top-level `## /api/images quickstart` heading with the same content.

- [ ] **Step 13.2: Update the decomposition status row**

Edit `docs/superpowers/plans/2026-04-22-v0.1-plan-decomposition.md`. Replace the existing **D** rows in both tables.

In the "Plan overview (A–I)" table, change the row to:

```markdown
| **D** | ImageStoreService | A, B | After expose, FITS + thumbnail are saved and retrievable via `/api/images/*`. Implemented: [2026-04-22-nocs-image-store.md](./2026-04-22-nocs-image-store.md). |
```

In the "Current status" table near the bottom, replace the `D–I` summary row with explicit rows:

```markdown
| D | Yes | [2026-04-22-nocs-image-store.md](./2026-04-22-nocs-image-store.md) |
| E–I | No | Author with the `writing-plans` skill when starting that slice |
```

- [ ] **Step 13.3: Run a sanity check**

Run: `./gradlew check`
Expected: BUILD SUCCESSFUL — no Java changes here, just docs.

- [ ] **Step 13.4: Commit**

```bash
git add README.md \
        docs/superpowers/plans/2026-04-22-v0.1-plan-decomposition.md
git commit -m "docs: README quickstart for /api/images and Plan D status update"
```

---

## Self-Review Notes

**Spec coverage** — Plan D maps to:

- §8.2 image endpoints (`GET /api/images/{id}.fits`, `/thumb.jpg`) — Task 10 (plus the list / get-JSON / delete extensions for usability).
- §12.1 `images` table — Task 1.
- §12.2 canonical on-disk layout under `data_dir/sessions/YYYY-MM-DD/<target>/<filter>_<exposure>s_<nnn>.fits` — Task 3.
- §13 `ImageStoreService` — Tasks 7–9.
- §15 server-stretched JPEG thumbnails on image arrival, no client-side FITS rendering — Tasks 6–8.
- §18.3 thumbnail stretch algorithm decision documented (MAD-percentile linear) — Task 6.

Deliberately **not** covered (belongs to later plans):

- Plate-solver header amendment — Plan E uses the `amendHeader(...)` stub left in `ImageStoreService`.
- Sequence-engine-driven metadata — Plan G will fill `prepareCapture(...)` from richer context without changing the contract.
- Multi-channel FITS / OSC debayering — explicitly out of v0.1.
- Web gallery UI — Plan H.

**Type / name consistency check:**

- Package root: `dev.nocs.image` (used in all tasks).
- DB columns: `session_id, device_id, filter, target, exposure_s, step_name, seq_index, fits_path, thumb_path, bytes, width, height, bitpix, date_obs, created_at` — matches `ImageRecord` field-by-field and the `ImageRepository` SQL.
- `CameraImageSink.accept(DeviceId, byte[], String)` — single signature, used by Plan B's adapter and now implemented by Plan D's `ImageStoreService`.
- `CaptureContext` fields `(filter, target, exposureSec, step, seq)` — same shape used by `PendingCaptures`, `ImagePaths.forCapture`, `ImageStoreService.prepareCapture`, `ExposeRequest`, and `CameraController.expose`.
- Event topic for image events: `Topic.CAMERA`, type `"image_saved"` (success) and `"image_store_failed"` (failure). Existing `"image_received"` from the Plan B `TempDirCameraImageSink` is retained for that fallback class but is not emitted by `ImageStoreService`.
- File-name format: `<filter>_<exposure>s_<nnn>.fits` and `<same>.thumb.jpg` — Tasks 3 and 7.
- HTTP content types: `application/fits` and `image/jpeg` — Task 10.

**No placeholders:** every step shows full code, exact gradle / curl commands, expected output, and a commit at the end. The only intentional stub is `ImageStoreService.amendHeader(...)` — documented as a hook for Plan E and unit-tested only via its `log.debug` no-op behaviour (no test required in Plan D).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-22-nocs-image-store.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
