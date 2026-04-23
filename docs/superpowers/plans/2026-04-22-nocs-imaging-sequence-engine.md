# NOCS ImagingService / Sequence Engine Implementation Plan (Plan G)

> **See also:** [NOCS v0.1 plan decomposition (A–I)](./2026-04-22-v0.1-plan-decomposition.md) — full roadmap and dependencies.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the `ImagingService` — the v0.1 sequence engine from spec §10. After this plan, an authenticated caller can `POST /api/sequences` with a JSON sequence (`target_id`, `dither`, `pre_steps`, `steps`), watch it run end-to-end against simulated devices, receive per-sub `CAMERA/image_saved` and `SEQUENCE/*` events, pause/resume/abort the run via REST, and have it honour `SEQUENCE/pause_requested`, `SEQUENCE/abort_requested`, and the `e_stop` path emitted by `SafetyService` (Plan F). The full v0.1 success criterion #4 ("autofocus + N × filter × exposure with dither") plus #5–#6 (rule trigger abort / e-stop abort) become exercisable via curl against a running server with only INDI simulators.

**Architecture:** One `ImagingService` owns a serial queue of at most one `SequenceRun` at a time. Runs execute on a JDK 25 virtual thread. A stateless `SequenceEngine` walks the run's state machine (`PENDING → RUNNING → PAUSED ↔ RUNNING → COMPLETED | ABORTED | FAILED`) and invokes collaborators for each step: a `DeviceSelector` resolves the mount/camera/filter wheel/focuser (single-connected heuristic or explicit IDs on the definition); a `SlewAndSync` helper runs the `slew_and_sync` pre-step (slew → settle → test-expose → plate-solve → `syncTo` when offset exceeds `nocs.imaging.sync-threshold-arcmin`); an `AutofocusStrategy` runs the `autofocus` pre-step (v0.1 ships `NoopAutofocusStrategy`, leaving a real hill-climb for v0.2); a `DitherStrategy` moves the mount by a pixel offset using the last plate-solution scale; an `ImageAwait` helper subscribes to `CAMERA/image_saved` and blocks the per-sub branch until the matching capture (filter + step + seq + target) arrives or times out. `ImagingService` also subscribes to `Topic.SEQUENCE` for `pause_requested` and `abort_requested` — those are honoured at the next safe boundary (between subs) or, for abort, by calling `camera.abortExposure()` plus transitioning the run immediately. E-stop arrives as the same `abort_requested` event (dispatched by `SafetyActionDispatcher.eStop`), but the device-level abort/park/E_STOPPED transitions were already done by the dispatcher itself — the engine only needs to mark its run `ABORTED`. Sequence rows persist in a new `sequences` table (Flyway V5) so history survives restart; live progress is in memory.

**Tech Stack:**
- JDK 25 + Spring Boot 3.5 (from Plan A)
- Project Reactor `EventBus` (from Plan A) — `SEQUENCE` + `CAMERA` + `MOUNT` + `FOCUSER` + `FILTERWHEEL` topics
- Jackson `ObjectMapper` (already on classpath) for `definition_json` round-trips
- Flyway (migration `V5__sequences.sql`)
- Virtual threads for the sequence runner; `ReentrantLock` + `Condition` for pause/resume coordination
- JUnit 5, AssertJ, Spring `MockMvc`, Awaitility, `reactor-test` (already present)
- **No new runtime deps.**

## Scope

### In scope for Plan G

1. New domain types in `dev.nocs.imaging`: `SequenceDefinition`, `SequenceStep`, `PreStep` (sealed with `SlewAndSyncStep`, `AutofocusStep`), `DitherOptions`, `SequenceStatus`, `SequenceRun`, `SequenceProgress`.
2. Flyway migration `V5__sequences.sql` — one table `sequences` (id, session_id, name, definition_json, status, failure_reason, created_at, started_at, finished_at, current_step_index, current_sub_index, subs_completed, subs_total).
3. `SequenceRepository` (JDBC) — insert, update status, update progress, find by id, list with filters.
4. New config block `nocs.imaging.*`:
   - `slew-settle-ms` — ms to wait after mount reports `TRACKING` before the test exposure (default 2000).
   - `sync-threshold-arcmin` — if the post-slew solve places us more than this far from the target, `syncTo` and re-sanity-check (default 1.0).
   - `post-slew-solve-timeout-sec` — per-attempt plate-solve timeout during `slew_and_sync` (default 30).
   - `test-exposure-sec` — exposure length for the `slew_and_sync` test frame (default 2.0).
   - `dither-settle-ms` — ms to wait after a dither slew completes before unblocking the next sub (default 2000).
   - `image-await-timeout-ms` — max wait for `CAMERA/image_saved` matching a sub (default `max(exposure_s*2, 30s) + 10s`).
   - `autofocus.strategy` — `noop` (default) or `sweep` (v0.2; this plan ships `noop` only but keeps the seam).
5. REST surface under `/api/sequences` (spec §8.2):
   - `POST /api/sequences` — body `SequenceDefinitionDto`; returns `SequenceView` with `id`, `status=RUNNING`.
   - `GET /api/sequences` — list recent (query params `session_id`, `limit`, `offset`).
   - `GET /api/sequences/{id}` — full view.
   - `POST /api/sequences/{id}/pause`
   - `POST /api/sequences/{id}/resume`
   - `POST /api/sequences/{id}/abort` — body `AbortRequest { reason? }`.
6. `ImagingService` bus subscriptions (spec §6, §10.2):
   - `SEQUENCE/pause_requested` from the `SafetyActionDispatcher` (reason carries `rule:<name>`) → cooperatively pause the current run at the next sub boundary.
   - `SEQUENCE/abort_requested` → mark current run `ABORTED` immediately; call `camera.abortExposure()` on the active camera if still `EXPOSING` (best-effort; dispatcher may have beaten us to it); emit `sequence_aborted {reason}` on the bus.
7. `SEQUENCE` topic event emissions (v0.1 vocabulary):
   - `sequence_submitted`, `sequence_started`, `sequence_completed`, `sequence_failed`, `sequence_aborted`
   - `prestep_started`, `prestep_completed`, `prestep_failed`
   - `slew_started`, `slew_completed`, `plate_solve_attempt`, `plate_solve_result`, `sync_applied`
   - `autofocus_started`, `autofocus_completed`
   - `step_started`, `step_completed`
   - `sub_started`, `sub_completed`, `sub_failed`
   - `dither_started`, `dither_completed`
   - `sequence_paused`, `sequence_resumed`
   - `target_active` — emitted when a run starts so the `altitude_below` rules in `SafetyService` pick up the current target.
8. Device selection (one mount, one camera, one filter wheel, one focuser — spec §1 target user). Sequence definition may pin an explicit `device_ids` block; otherwise `DeviceSelector` picks the single connected device of each required kind and fails with a clear error otherwise.
9. Pre-steps (spec §10.1):
   - `slew_and_sync` — resolve target via `TargetService.resolveById`, slew, settle, test-expose (using `ImageStoreService.prepareCapture` with a synthetic step `__prestep`), plate-solve the captured FITS via `PlateSolvingService.solve`, `syncTo` if offset > threshold, emit events throughout. On solve failure, retry once; on second failure emit `prestep_failed` and transition the run to `FAILED`.
   - `autofocus` — delegate to the injected `AutofocusStrategy`. `NoopAutofocusStrategy` emits start/complete immediately and leaves the focuser untouched. (Seam documented.)
10. Imaging loop (spec §10.2):
    - For each `SequenceStep`: select the filter slot by name (look up in `FilterWheel.slotNames()`), wait for `FILTERWHEEL` to reach `IDLE`, then loop `count` times.
    - Each sub: `ImageStoreService.prepareCapture(camera, CaptureContext(filter, target, exposure_s, step_name, seq))` then `camera.expose(exposure_s)`, then `ImageAwait.waitFor(...)` to block until `CAMERA/image_saved` arrives with the matching `step` + `seq` + `target` payload (or timeout → sub failure).
    - After a sub, if `DitherOptions.enabled` and `seq % every_n_subs == 0`, invoke `DitherStrategy.dither(mount, offsetPixels, lastSolution)` and wait `dither-settle-ms`.
    - Between subs, consult the pause latch; if set, transition `RUNNING → PAUSED`, emit `sequence_paused`, and block on a `Condition` until `resume()` or `abort()` fires.
    - After the last sub of the last step: `RUNNING → COMPLETED`, emit `sequence_completed`.
11. Dithering (spec §10.3) — ship `PixelOffsetDitherStrategy`: compute `arcsecOffset = ditherPixels × lastSolution.pixelScaleArcsecPerPx`, convert to RA/Dec delta on the plane tangent to the current pointing, call `mount.slew(currentRaHours + ΔraHours, currentDecDeg + ΔdecDeg)`, settle. No guider feedback loop. If no plate solution is available yet (first sub, solve failed, etc.) emit `dither_skipped` and continue.
12. Abort semantics:
    - User abort via REST → `camera.abortExposure()` (best-effort), mark `ABORTED`, emit `sequence_aborted {reason:"user:…"}`. Does **not** park the mount (spec §6.3 is the authority for parking — that's Plan F's concern).
    - Safety abort via `SEQUENCE/abort_requested` → mark `ABORTED`, emit `sequence_aborted {reason:<incoming>}`. Mount park already done by `SafetyActionDispatcher` where appropriate.
    - E-stop → arrives as `abort_requested` with `reason:"e_stop"`. Same code path.
13. Session wiring:
    - On `sequence_started`, attach the run's DB row to the current `SessionService.current()` (if any) by writing `session_id`; also call `sessionService.logEvent("sequence", "started", payload)`.
    - On terminal events (`completed` / `aborted` / `failed`), call `sessionService.logEvent(...)` similarly.
14. End-to-end integration tests:
    - **Happy path** — fake mount/camera/filter-wheel/focuser + fake plate solver returning a canned solution. Post a 2-step sequence (L × 2 subs, R × 1 sub) with `slew_and_sync` + `autofocus` pre-steps and dither enabled every sub. Assert ordering of `SEQUENCE/*` events, three saved images (via `GET /api/images`), and `status=COMPLETED`.
    - **Pause/resume** — submit a sequence of 3 subs, post `pause` after sub 1 completes, assert `SEQUENCE/sequence_paused`, wait, post `resume`, assert the remaining subs run and `status=COMPLETED`.
    - **Rule-triggered abort** — load a safety rule `rain → abort_and_park`, submit a 3-sub sequence, post a `rain` sensor reading after sub 1, assert `status=ABORTED`, assert `sequence_aborted.reason` contains `rule:rain`, assert mount had `park()` called.
    - **E-stop abort** — same as above but rule `rain → e_stop`; assert `status=ABORTED`, camera `emergencyStop`/`abortExposure` invoked, mount `park` invoked.
15. Documentation:
    - Update `docs/superpowers/plans/2026-04-22-v0.1-plan-decomposition.md` (status table) to mark Plan G written.
    - Add a "Sequences" section to `README.md` with a curl walkthrough.

### Explicitly out of scope for Plan G

- **Real autofocus strategy** — `NoopAutofocusStrategy` is the v0.1 default. `SweepAutofocusStrategy` (HFR-based hill-climb) is deferred to v0.2. The `AutofocusStrategy` interface is the seam; swapping implementations is a bean replacement.
- **Guider feedback loop** for dithering — spec §10.3 explicitly says "no guiding feedback loop" in v0.1.
- **Calibration frames** (darks, flats, bias) — v0.1 non-goal.
- **Meridian flip automation** — v0.1 non-goal.
- **Multi-target scheduler** — v0.1 non-goal; exactly one target per sequence.
- **Parallel sequences** — v0.1 is single-user on LAN; the engine rejects a second `POST /api/sequences` with HTTP 409 while a run is `RUNNING` or `PAUSED`.
- **Horizon-mask-aware altitude decisions during imaging** — Plan F landed a flat `altitude_below: <deg>` rule and publishes `SEQUENCE/abort_requested` when it fires. The engine just consumes that, it does not compute altitude itself.
- **Per-filter re-autofocus between steps** — spec §10.2 says "v0.2 feature flag; v0.1 does autofocus once at pre-step time only".
- **Web UI for sequences** — Plan H.
- **Between-sub plate-solve and recenter** — not needed for v0.1 dither; can be layered on top of the same event seam later.
- **Persisting per-sub timings or per-step image ids** beyond what's already recorded on the `images` table — the current `images.step_name` + `images.session_id` already link subs to the run via its session.

## File Structure

All paths are relative to the repo root (`/home/jorjazo/dev/nocs/nocs`). Every file below has one responsibility; none should exceed ~300 lines.

**New main sources** (`src/main/java/dev/nocs/imaging/`):

- `SequenceStatus.java` — enum `PENDING, RUNNING, PAUSED, COMPLETED, ABORTED, FAILED`.
- `DitherOptions.java` — record `(boolean enabled, int pixels, int everyNSubs)` with validation and `disabled()` factory.
- `PreStep.java` — sealed interface with permits `SlewAndSyncStep` (marker record) and `AutofocusStep` (marker record) + `wire()` / `fromWire(String)` round-trip.
- `SequenceStep.java` — record `(String filter, double exposureSec, int count, String name)`; `name` defaults to `"step-<filter>"` if blank.
- `SequenceDefinition.java` — record `(String name, String targetId, DitherOptions dither, List<PreStep> preSteps, List<SequenceStep> steps, DeviceIds deviceIds)` + nested `DeviceIds(String mountId, cameraId, filterWheelId, focuserId)` (any may be null). Compact constructor validates non-empty steps, non-null target id, and `dither.everyNSubs >= 1` when `enabled`.
- `SequenceRun.java` — DB row record `(Long id, Long sessionId, String name, String definitionJson, SequenceStatus status, String failureReason, Instant createdAt, Instant startedAt, Instant finishedAt, Integer currentStepIndex, Integer currentSubIndex, int subsCompleted, int subsTotal)`; `forInsert(...)` factory.
- `SequenceProgress.java` — read-only in-memory view `(long runId, SequenceStatus status, int currentStepIndex, int currentSubIndex, int subsCompleted, int subsTotal, String message)`.
- `SequenceRepository.java` — JDBC: `insert`, `updateStatus`, `updateProgress`, `findById`, `list(Filters)`.
- `DeviceSelector.java` — resolves `Mount`, `Camera`, `FilterWheel`, `Focuser` from `DeviceRegistry` given optional pinned IDs; throws `SequenceSetupException` on ambiguity / missing device.
- `SequenceSetupException.java` — `RuntimeException` with a `kind` ("missing_device", "multiple_devices", "target_not_found", "target_unresolvable", "device_not_connected"). Thrown before the run transitions to `RUNNING`.
- `ImageAwait.java` — helper with `CompletableFuture<ImageSavedEvent> waitFor(DeviceId camera, String target, String step, int seq, Duration timeout)`; internally subscribes to `Topic.CAMERA/image_saved`.
- `DitherStrategy.java` — interface `DitherResult dither(Mount m, PlateSolution lastSolution, double currentRaHours, double currentDecDeg, int pixelOffset, long settleMs)`; returns `DitherResult(double newRaHours, double newDecDeg, boolean skipped, String skipReason)`.
- `PixelOffsetDitherStrategy.java` — default impl; pseudo-random XY offset mapped to RA/Dec via plate scale and a tangent-plane approximation.
- `AutofocusStrategy.java` — interface `AutofocusResult run(Focuser f, Camera c, AutofocusContext ctx)` + record `AutofocusResult(int bestPosition, int pointsTried, long durationMs)` + record `AutofocusContext(String target, Instant at)`.
- `NoopAutofocusStrategy.java` — no-op impl; returns `AutofocusResult(f.currentPosition(), 0, 0)`.
- `SlewAndSync.java` — stateless helper class with `execute(SlewAndSyncContext)` that drives slew → settle → test-expose → solve → optional sync.
- `SequenceEngine.java` — the core loop; package-private (only `ImagingService` calls `run(...)`). Accepts the `SequenceRun`, resolved devices, strategies, collaborators, plus a `PauseAbortLatch`.
- `PauseAbortLatch.java` — small synchronisation utility. Methods: `pause()`, `resume()`, `abort(String reason)`, `isAbortRequested()`, `awaitIfPaused()`. Uses `ReentrantLock` + `Condition`.
- `ImagingService.java` — public facade: `submit(SequenceDefinition)`, `pause(long)`, `resume(long)`, `abort(long, String)`, `find(long)`, `list(Filters)`, `progress(long)`. Manages the single active run + bus subscriptions.
- `api/SequenceController.java` — six REST endpoints.
- `api/dto/SequenceDefinitionDto.java`, `api/dto/SequenceStepDto.java`, `api/dto/PreStepDto.java`, `api/dto/DitherDto.java`, `api/dto/DeviceIdsDto.java`, `api/dto/SequenceView.java`, `api/dto/AbortRequest.java`, `api/dto/SequenceFilters.java` — request/response DTOs.

**Modified main sources:**

- `config/NocsProperties.java` — add `Imaging` subrecord (defaults specified in Scope #4).
- `config/AppBeansConfig.java` — wire `SequenceRepository`, `DeviceSelector`, `ImageAwait`, `DitherStrategy`, `AutofocusStrategy` (strategy-by-name switch), `SlewAndSync`, `SequenceEngine` factory, `ImagingService`.
- `src/main/resources/application.yaml` — append `nocs.imaging.*` defaults.
- `src/main/resources/config.example.yaml` — append a documented `imaging:` block.

**Resources:**

- `src/main/resources/db/migration/V5__sequences.sql` — the sequence table DDL.

**New test sources** (`src/test/java/dev/nocs/imaging/`):

- `SequenceStatusTest.java` — enum round-trip.
- `DitherOptionsTest.java` — validation + `disabled()`.
- `PreStepTest.java` — wire/fromWire + sealed-interface ergonomics.
- `SequenceStepTest.java` — name defaulting + count > 0 validation.
- `SequenceDefinitionTest.java` — non-empty steps, target id required, dither every-n default.
- `SequenceRepositoryTest.java` — CRUD, status transitions, list filters.
- `ImagingConfigTest.java` — binds `nocs.imaging.*` from `@TestPropertySource`.
- `DeviceSelectorTest.java` — single-mount picking + ambiguity + explicit-pin + unconnected.
- `ImageAwaitTest.java` — matches on `(device, step, seq, target)`; ignores noise; times out; unsubscribes.
- `PixelOffsetDitherStrategyTest.java` — deterministic offset from a fixed seed; scale math.
- `NoopAutofocusStrategyTest.java` — returns current position, emits no side effects.
- `SlewAndSyncTest.java` — drives a fake mount + fake camera + canned plate solver.
- `PauseAbortLatchTest.java` — blocks-then-releases; abort short-circuits pause.
- `SequenceEngineTest.java` — unit-level, drives a small definition against fakes; covers loop, pause, abort, dither-skip-when-no-solution.
- `ImagingServiceTest.java` — submit while another run is active returns conflict; bus subscribe handles `SEQUENCE/pause_requested` + `abort_requested`.
- `api/SequenceControllerTest.java` — MockMvc: 401 without bearer, 201 create, 409 second submit, 404 unknown id, 400 invalid body.
- `IntegrationHappyPathSequenceTest.java` — full Spring context, fake devices, canned solver; 2-step sequence runs to `COMPLETED`.
- `IntegrationPauseResumeSequenceTest.java` — pause after sub 1, resume, complete.
- `IntegrationRuleAbortSequenceTest.java` — safety rule `rain → abort_and_park` fires mid-sequence; run becomes `ABORTED`; mount parked.
- `IntegrationEStopSequenceTest.java` — safety rule `rain → e_stop` fires mid-sequence; run becomes `ABORTED`; camera emergencyStop + mount park invoked.

**New test resources:**

- `src/test/resources/imaging/sequence-minimal.json` — one-step, one-sub definition used by several tests.
- `src/test/resources/imaging/mini-fits-1x1.bin` — reused via `dev.nocs.image.MiniFits` (no new file needed — `MiniFits` already synthesises bytes on the fly; kept here for explicitness).

## Tasks

Each task is self-contained: files listed, TDD steps with complete code, exact commands with expected output, and a commit at the end. Tasks 1–4 land domain + persistence + config; tasks 5–9 ship the helpers and strategies; tasks 10–11 ship the engine; task 12 ships the service; tasks 13–14 wire beans + REST; tasks 15–18 cover integration tests + docs.

A shared test fixture (`FakeDeviceFixture`) is introduced in Task 15 and reused by Tasks 16–18. Unit tests in Tasks 6–11 use their own small fakes (one per file) to keep them focused.

---

### Task 1: Flyway `V5__sequences` migration

**Files:**
- Create: `src/main/resources/db/migration/V5__sequences.sql`
- Create: `src/test/java/dev/nocs/imaging/SequencesMigrationTest.java`

- [ ] **Step 1.1: Write the failing test**

Create `src/test/java/dev/nocs/imaging/SequencesMigrationTest.java`:

```java
package dev.nocs.imaging;

import javax.sql.DataSource;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
class SequencesMigrationTest {

    @Autowired
    DataSource ds;

    @Test
    void sequencesTableHasExpectedColumns() {
        JdbcTemplate jdbc = new JdbcTemplate(ds);
        var cols = jdbc.queryForList("PRAGMA table_info(sequences)");
        var names = cols.stream().map(m -> (String) m.get("name")).toList();
        assertThat(names).contains(
                "id", "session_id", "name", "definition_json", "status",
                "failure_reason", "created_at", "started_at", "finished_at",
                "current_step_index", "current_sub_index",
                "subs_completed", "subs_total");
    }
}
```

- [ ] **Step 1.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.imaging.SequencesMigrationTest'`
Expected: FAIL — `no such table: sequences`.

- [ ] **Step 1.3: Create the migration**

Create `src/main/resources/db/migration/V5__sequences.sql`:

```sql
CREATE TABLE sequences (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id           INTEGER REFERENCES sessions(id),
    name                 TEXT    NOT NULL,
    definition_json      TEXT    NOT NULL,
    status               TEXT    NOT NULL DEFAULT 'PENDING',
    failure_reason       TEXT,
    created_at           TEXT    NOT NULL DEFAULT (datetime('now')),
    started_at           TEXT,
    finished_at          TEXT,
    current_step_index   INTEGER,
    current_sub_index    INTEGER,
    subs_completed       INTEGER NOT NULL DEFAULT 0,
    subs_total           INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_sequences_session_id ON sequences(session_id);
CREATE INDEX idx_sequences_status     ON sequences(status);
CREATE INDEX idx_sequences_created_at ON sequences(created_at);
```

- [ ] **Step 1.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.imaging.SequencesMigrationTest'`
Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 1.5: Commit**

```bash
git add src/main/resources/db/migration/V5__sequences.sql \
        src/test/java/dev/nocs/imaging/SequencesMigrationTest.java
git commit -m "feat(imaging): V5 migration for sequences table"
```

---

### Task 2: Domain records (`SequenceStatus`, `DitherOptions`, `PreStep`, `SequenceStep`, `SequenceDefinition`, `SequenceRun`, `SequenceProgress`)

**Files:**
- Create: `src/main/java/dev/nocs/imaging/SequenceStatus.java`
- Create: `src/main/java/dev/nocs/imaging/DitherOptions.java`
- Create: `src/main/java/dev/nocs/imaging/PreStep.java`
- Create: `src/main/java/dev/nocs/imaging/SequenceStep.java`
- Create: `src/main/java/dev/nocs/imaging/SequenceDefinition.java`
- Create: `src/main/java/dev/nocs/imaging/SequenceRun.java`
- Create: `src/main/java/dev/nocs/imaging/SequenceProgress.java`
- Create: `src/test/java/dev/nocs/imaging/SequenceStatusTest.java`
- Create: `src/test/java/dev/nocs/imaging/DitherOptionsTest.java`
- Create: `src/test/java/dev/nocs/imaging/PreStepTest.java`
- Create: `src/test/java/dev/nocs/imaging/SequenceStepTest.java`
- Create: `src/test/java/dev/nocs/imaging/SequenceDefinitionTest.java`

- [ ] **Step 2.1: Write the failing tests**

Create `src/test/java/dev/nocs/imaging/SequenceStatusTest.java`:

```java
package dev.nocs.imaging;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SequenceStatusTest {

    @Test
    void terminalAndActive() {
        assertThat(SequenceStatus.RUNNING.isTerminal()).isFalse();
        assertThat(SequenceStatus.PAUSED.isTerminal()).isFalse();
        assertThat(SequenceStatus.PENDING.isTerminal()).isFalse();
        assertThat(SequenceStatus.COMPLETED.isTerminal()).isTrue();
        assertThat(SequenceStatus.ABORTED.isTerminal()).isTrue();
        assertThat(SequenceStatus.FAILED.isTerminal()).isTrue();

        assertThat(SequenceStatus.RUNNING.isActive()).isTrue();
        assertThat(SequenceStatus.PAUSED.isActive()).isTrue();
        assertThat(SequenceStatus.PENDING.isActive()).isFalse();
        assertThat(SequenceStatus.COMPLETED.isActive()).isFalse();
    }

    @Test
    void wireRoundTrip() {
        for (SequenceStatus s : SequenceStatus.values()) {
            assertThat(SequenceStatus.fromWire(s.wire())).isEqualTo(s);
        }
    }
}
```

Create `src/test/java/dev/nocs/imaging/DitherOptionsTest.java`:

```java
package dev.nocs.imaging;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class DitherOptionsTest {

    @Test
    void disabledFactory() {
        DitherOptions d = DitherOptions.disabled();
        assertThat(d.enabled()).isFalse();
        assertThat(d.pixels()).isZero();
        assertThat(d.everyNSubs()).isEqualTo(1);
    }

    @Test
    void validatesEnabledRequiresPositivePixels() {
        assertThatThrownBy(() -> new DitherOptions(true, 0, 1))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("pixels");
    }

    @Test
    void validatesEveryNSubs() {
        assertThatThrownBy(() -> new DitherOptions(true, 10, 0))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("everyNSubs");
        assertThat(new DitherOptions(true, 10, 1).everyNSubs()).isEqualTo(1);
        assertThat(new DitherOptions(true, 10, 3).everyNSubs()).isEqualTo(3);
    }

    @Test
    void disabledIgnoresPixelsAndEveryN() {
        DitherOptions d = new DitherOptions(false, -1, 0);
        assertThat(d.enabled()).isFalse();
        assertThat(d.everyNSubs()).isEqualTo(1);
    }
}
```

Create `src/test/java/dev/nocs/imaging/PreStepTest.java`:

```java
package dev.nocs.imaging;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class PreStepTest {

    @Test
    void slewAndSync() {
        PreStep s = new PreStep.SlewAndSyncStep();
        assertThat(s.wire()).isEqualTo("slew_and_sync");
    }

    @Test
    void autofocus() {
        PreStep s = new PreStep.AutofocusStep();
        assertThat(s.wire()).isEqualTo("autofocus");
    }

    @Test
    void fromWire() {
        assertThat(PreStep.fromWire("slew_and_sync")).isInstanceOf(PreStep.SlewAndSyncStep.class);
        assertThat(PreStep.fromWire("autofocus")).isInstanceOf(PreStep.AutofocusStep.class);
    }

    @Test
    void fromWireRejectsUnknown() {
        assertThatThrownBy(() -> PreStep.fromWire("teleport"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("teleport");
    }
}
```

Create `src/test/java/dev/nocs/imaging/SequenceStepTest.java`:

```java
package dev.nocs.imaging;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class SequenceStepTest {

    @Test
    void nameDefaultsToStepFilter() {
        SequenceStep s = new SequenceStep("L", 120.0, 5, null);
        assertThat(s.name()).isEqualTo("step-L");
    }

    @Test
    void blankNameReplaced() {
        SequenceStep s = new SequenceStep("Ha", 60.0, 2, "   ");
        assertThat(s.name()).isEqualTo("step-Ha");
    }

    @Test
    void explicitNameKept() {
        SequenceStep s = new SequenceStep("R", 180, 10, "red-wide");
        assertThat(s.name()).isEqualTo("red-wide");
    }

    @Test
    void validatesCountPositive() {
        assertThatThrownBy(() -> new SequenceStep("L", 120, 0, null))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("count");
    }

    @Test
    void validatesExposurePositive() {
        assertThatThrownBy(() -> new SequenceStep("L", 0, 1, null))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("exposureSec");
    }

    @Test
    void validatesFilterNonBlank() {
        assertThatThrownBy(() -> new SequenceStep("  ", 10, 1, null))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("filter");
    }
}
```

Create `src/test/java/dev/nocs/imaging/SequenceDefinitionTest.java`:

```java
package dev.nocs.imaging;

import java.util.List;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class SequenceDefinitionTest {

    @Test
    void normalisesNullCollectionsAndDeviceIds() {
        SequenceDefinition d = new SequenceDefinition(
                null,
                "messier:M31",
                null,
                null,
                List.of(new SequenceStep("L", 60, 1, null)),
                null);
        assertThat(d.name()).isEqualTo("sequence-messier:M31");
        assertThat(d.dither().enabled()).isFalse();
        assertThat(d.preSteps()).isEmpty();
        assertThat(d.deviceIds()).isNotNull();
        assertThat(d.deviceIds().mountId()).isNull();
    }

    @Test
    void stepsRequired() {
        assertThatThrownBy(() -> new SequenceDefinition(
                "s", "messier:M31", null, List.of(), List.of(), null))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("steps");
    }

    @Test
    void targetIdRequired() {
        assertThatThrownBy(() -> new SequenceDefinition(
                "s", null, null, List.of(), List.of(new SequenceStep("L", 30, 1, null)), null))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("targetId");
    }

    @Test
    void subsTotal() {
        SequenceDefinition d = new SequenceDefinition(
                "s", "messier:M31", null, List.of(),
                List.of(new SequenceStep("L", 60, 3, null), new SequenceStep("R", 60, 2, null)),
                null);
        assertThat(d.totalSubs()).isEqualTo(5);
    }
}
```

- [ ] **Step 2.2: Run — expect failures**

Run: `./gradlew test --tests 'dev.nocs.imaging.SequenceStatusTest' --tests 'dev.nocs.imaging.DitherOptionsTest' --tests 'dev.nocs.imaging.PreStepTest' --tests 'dev.nocs.imaging.SequenceStepTest' --tests 'dev.nocs.imaging.SequenceDefinitionTest'`
Expected: compile failures — classes do not exist.

- [ ] **Step 2.3: Implement `SequenceStatus`**

Create `src/main/java/dev/nocs/imaging/SequenceStatus.java`:

```java
package dev.nocs.imaging;

public enum SequenceStatus {
    PENDING,
    RUNNING,
    PAUSED,
    COMPLETED,
    ABORTED,
    FAILED;

    public boolean isTerminal() {
        return this == COMPLETED || this == ABORTED || this == FAILED;
    }

    public boolean isActive() {
        return this == RUNNING || this == PAUSED;
    }

    public String wire() {
        return name();
    }

    public static SequenceStatus fromWire(String s) {
        if (s == null) throw new IllegalArgumentException("status is null");
        return SequenceStatus.valueOf(s.trim().toUpperCase());
    }
}
```

- [ ] **Step 2.4: Implement `DitherOptions`**

Create `src/main/java/dev/nocs/imaging/DitherOptions.java`:

```java
package dev.nocs.imaging;

public record DitherOptions(boolean enabled, int pixels, int everyNSubs) {

    public DitherOptions {
        if (enabled && pixels <= 0) {
            throw new IllegalArgumentException("pixels must be > 0 when enabled, got " + pixels);
        }
        if (enabled && everyNSubs <= 0) {
            throw new IllegalArgumentException("everyNSubs must be >= 1 when enabled, got " + everyNSubs);
        }
        if (!enabled) {
            pixels = 0;
            everyNSubs = 1;
        }
    }

    public static DitherOptions disabled() {
        return new DitherOptions(false, 0, 1);
    }

    public boolean shouldDither(int subIndex) {
        if (!enabled) return false;
        return subIndex >= 1 && (subIndex % everyNSubs) == 0;
    }
}
```

- [ ] **Step 2.5: Implement `PreStep`**

Create `src/main/java/dev/nocs/imaging/PreStep.java`:

```java
package dev.nocs.imaging;

public sealed interface PreStep
        permits PreStep.SlewAndSyncStep, PreStep.AutofocusStep {

    String wire();

    record SlewAndSyncStep() implements PreStep {
        @Override
        public String wire() {
            return "slew_and_sync";
        }
    }

    record AutofocusStep() implements PreStep {
        @Override
        public String wire() {
            return "autofocus";
        }
    }

    static PreStep fromWire(String wire) {
        if (wire == null) throw new IllegalArgumentException("prestep type is null");
        return switch (wire.trim().toLowerCase()) {
            case "slew_and_sync" -> new SlewAndSyncStep();
            case "autofocus" -> new AutofocusStep();
            default -> throw new IllegalArgumentException("unknown prestep: " + wire);
        };
    }
}
```

- [ ] **Step 2.6: Implement `SequenceStep`**

Create `src/main/java/dev/nocs/imaging/SequenceStep.java`:

```java
package dev.nocs.imaging;

public record SequenceStep(String filter, double exposureSec, int count, String name) {

    public SequenceStep {
        if (filter == null || filter.isBlank()) {
            throw new IllegalArgumentException("filter must be non-blank");
        }
        if (exposureSec <= 0) {
            throw new IllegalArgumentException("exposureSec must be > 0, got " + exposureSec);
        }
        if (count <= 0) {
            throw new IllegalArgumentException("count must be > 0, got " + count);
        }
        if (name == null || name.isBlank()) {
            name = "step-" + filter;
        }
    }
}
```

- [ ] **Step 2.7: Implement `SequenceDefinition`**

Create `src/main/java/dev/nocs/imaging/SequenceDefinition.java`:

```java
package dev.nocs.imaging;

import java.util.List;

public record SequenceDefinition(
        String name,
        String targetId,
        DitherOptions dither,
        List<PreStep> preSteps,
        List<SequenceStep> steps,
        DeviceIds deviceIds) {

    public SequenceDefinition {
        if (targetId == null || targetId.isBlank()) {
            throw new IllegalArgumentException("targetId is required");
        }
        if (steps == null || steps.isEmpty()) {
            throw new IllegalArgumentException("steps must contain at least one entry");
        }
        if (dither == null) dither = DitherOptions.disabled();
        if (preSteps == null) preSteps = List.of();
        if (deviceIds == null) deviceIds = DeviceIds.empty();
        if (name == null || name.isBlank()) {
            name = "sequence-" + targetId;
        }
        preSteps = List.copyOf(preSteps);
        steps = List.copyOf(steps);
    }

    public int totalSubs() {
        return steps.stream().mapToInt(SequenceStep::count).sum();
    }

    public record DeviceIds(String mountId, String cameraId, String filterWheelId, String focuserId) {
        public static DeviceIds empty() {
            return new DeviceIds(null, null, null, null);
        }
    }
}
```

- [ ] **Step 2.8: Implement `SequenceRun` + `SequenceProgress`**

Create `src/main/java/dev/nocs/imaging/SequenceRun.java`:

```java
package dev.nocs.imaging;

import java.time.Instant;

public record SequenceRun(
        Long id,
        Long sessionId,
        String name,
        String definitionJson,
        SequenceStatus status,
        String failureReason,
        Instant createdAt,
        Instant startedAt,
        Instant finishedAt,
        Integer currentStepIndex,
        Integer currentSubIndex,
        int subsCompleted,
        int subsTotal) {

    public static SequenceRun forInsert(
            Long sessionId, String name, String definitionJson, int subsTotal) {
        return new SequenceRun(
                null, sessionId, name, definitionJson,
                SequenceStatus.PENDING, null,
                null, null, null, null, null, 0, subsTotal);
    }
}
```

Create `src/main/java/dev/nocs/imaging/SequenceProgress.java`:

```java
package dev.nocs.imaging;

public record SequenceProgress(
        long runId,
        SequenceStatus status,
        int currentStepIndex,
        int currentSubIndex,
        int subsCompleted,
        int subsTotal,
        String message) {

    public static SequenceProgress initial(long runId, int subsTotal) {
        return new SequenceProgress(runId, SequenceStatus.PENDING, 0, 0, 0, subsTotal, "submitted");
    }
}
```

- [ ] **Step 2.9: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.imaging.SequenceStatusTest' --tests 'dev.nocs.imaging.DitherOptionsTest' --tests 'dev.nocs.imaging.PreStepTest' --tests 'dev.nocs.imaging.SequenceStepTest' --tests 'dev.nocs.imaging.SequenceDefinitionTest'`
Expected: all pass.

- [ ] **Step 2.10: Commit**

```bash
git add src/main/java/dev/nocs/imaging/ src/test/java/dev/nocs/imaging/
git commit -m "feat(imaging): domain records for sequences + pre-steps + dither"
```

---

### Task 3: `SequenceRepository` (JDBC)

**Files:**
- Create: `src/main/java/dev/nocs/imaging/SequenceRepository.java`
- Create: `src/test/java/dev/nocs/imaging/SequenceRepositoryTest.java`

- [ ] **Step 3.1: Write the failing test**

Create `src/test/java/dev/nocs/imaging/SequenceRepositoryTest.java`:

```java
package dev.nocs.imaging;

import java.time.Instant;
import java.util.List;
import javax.sql.DataSource;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
class SequenceRepositoryTest {

    @Autowired
    DataSource ds;

    @Test
    void insertFindUpdate() {
        SequenceRepository repo = new SequenceRepository(ds);
        long id = repo.insert(SequenceRun.forInsert(null, "s1", "{}", 5));
        assertThat(id).isPositive();

        SequenceRun r = repo.findById(id).orElseThrow();
        assertThat(r.name()).isEqualTo("s1");
        assertThat(r.status()).isEqualTo(SequenceStatus.PENDING);
        assertThat(r.subsTotal()).isEqualTo(5);
        assertThat(r.createdAt()).isNotNull();

        repo.updateStatus(id, SequenceStatus.RUNNING, null, Instant.parse("2026-04-22T20:00:00Z"), null);
        repo.updateProgress(id, 0, 1, 1);
        SequenceRun r2 = repo.findById(id).orElseThrow();
        assertThat(r2.status()).isEqualTo(SequenceStatus.RUNNING);
        assertThat(r2.startedAt()).isEqualTo(Instant.parse("2026-04-22T20:00:00Z"));
        assertThat(r2.currentStepIndex()).isZero();
        assertThat(r2.currentSubIndex()).isEqualTo(1);
        assertThat(r2.subsCompleted()).isEqualTo(1);

        repo.updateStatus(id, SequenceStatus.COMPLETED, null, null, Instant.parse("2026-04-22T20:10:00Z"));
        assertThat(repo.findById(id).orElseThrow().finishedAt())
                .isEqualTo(Instant.parse("2026-04-22T20:10:00Z"));
    }

    @Test
    void listByStatus() {
        SequenceRepository repo = new SequenceRepository(ds);
        long a = repo.insert(SequenceRun.forInsert(null, "a", "{}", 1));
        long b = repo.insert(SequenceRun.forInsert(null, "b", "{}", 1));
        repo.updateStatus(a, SequenceStatus.COMPLETED, null, null, Instant.now());
        List<SequenceRun> all = repo.list(new SequenceRepository.Filters(null, 100, 0));
        assertThat(all).extracting(SequenceRun::id).contains(a, b);
    }

    @Test
    void findByIdMissing() {
        SequenceRepository repo = new SequenceRepository(ds);
        assertThat(repo.findById(999_999)).isEmpty();
    }
}
```

- [ ] **Step 3.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.imaging.SequenceRepositoryTest'`
Expected: compile failure — `SequenceRepository` missing.

- [ ] **Step 3.3: Implement `SequenceRepository`**

Create `src/main/java/dev/nocs/imaging/SequenceRepository.java`:

```java
package dev.nocs.imaging;

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
import javax.sql.DataSource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

@Repository
public class SequenceRepository {

    private static final String INSERT_SQL =
            "INSERT INTO sequences (session_id, name, definition_json, status, subs_total)"
                    + " VALUES (?, ?, ?, ?, ?)";
    private static final String SELECT_SQL =
            "SELECT id, session_id, name, definition_json, status, failure_reason,"
                    + " created_at, started_at, finished_at,"
                    + " current_step_index, current_sub_index, subs_completed, subs_total"
                    + " FROM sequences";

    private final JdbcTemplate jdbc;

    public SequenceRepository(DataSource ds) {
        this.jdbc = new JdbcTemplate(ds);
    }

    public long insert(SequenceRun r) {
        return jdbc.execute((java.sql.Connection c) -> {
            try (var ps = c.prepareStatement(INSERT_SQL, Statement.RETURN_GENERATED_KEYS)) {
                if (r.sessionId() == null) ps.setNull(1, java.sql.Types.INTEGER);
                else ps.setLong(1, r.sessionId());
                ps.setString(2, r.name());
                ps.setString(3, r.definitionJson());
                ps.setString(4, r.status().wire());
                ps.setInt(5, r.subsTotal());
                ps.executeUpdate();
                try (ResultSet rs = ps.getGeneratedKeys()) {
                    if (rs.next()) return rs.getLong(1);
                    throw new SQLException("no generated key");
                }
            }
        });
    }

    public void updateStatus(long id, SequenceStatus status, String failureReason, Instant startedAt, Instant finishedAt) {
        jdbc.update(
                "UPDATE sequences SET status = ?, failure_reason = ?,"
                        + " started_at = COALESCE(?, started_at),"
                        + " finished_at = COALESCE(?, finished_at)"
                        + " WHERE id = ?",
                status.wire(),
                failureReason,
                startedAt == null ? null : toText(startedAt),
                finishedAt == null ? null : toText(finishedAt),
                id);
    }

    public void updateProgress(long id, int currentStepIndex, int currentSubIndex, int subsCompleted) {
        jdbc.update(
                "UPDATE sequences SET current_step_index = ?, current_sub_index = ?, subs_completed = ?"
                        + " WHERE id = ?",
                currentStepIndex,
                currentSubIndex,
                subsCompleted,
                id);
    }

    public Optional<SequenceRun> findById(long id) {
        List<SequenceRun> rs = jdbc.query(SELECT_SQL + " WHERE id = ?", ROW_MAPPER, id);
        return rs.stream().findFirst();
    }

    public List<SequenceRun> list(Filters f) {
        StringBuilder sql = new StringBuilder(SELECT_SQL);
        List<Object> args = new ArrayList<>();
        if (f.sessionId() != null) {
            sql.append(" WHERE session_id = ?");
            args.add(f.sessionId());
        }
        sql.append(" ORDER BY id DESC LIMIT ? OFFSET ?");
        args.add(Math.max(1, f.limit()));
        args.add(Math.max(0, f.offset()));
        return jdbc.query(sql.toString(), ROW_MAPPER, args.toArray());
    }

    public record Filters(Long sessionId, int limit, int offset) {}

    private static final RowMapper<SequenceRun> ROW_MAPPER = (rs, i) -> new SequenceRun(
            rs.getLong("id"),
            getNullableLong(rs, "session_id"),
            rs.getString("name"),
            rs.getString("definition_json"),
            SequenceStatus.fromWire(rs.getString("status")),
            rs.getString("failure_reason"),
            parseTs(rs.getString("created_at")),
            parseTs(rs.getString("started_at")),
            parseTs(rs.getString("finished_at")),
            getNullableInt(rs, "current_step_index"),
            getNullableInt(rs, "current_sub_index"),
            rs.getInt("subs_completed"),
            rs.getInt("subs_total"));

    private static Long getNullableLong(ResultSet rs, String col) throws SQLException {
        long v = rs.getLong(col);
        return rs.wasNull() ? null : v;
    }

    private static Integer getNullableInt(ResultSet rs, String col) throws SQLException {
        int v = rs.getInt(col);
        return rs.wasNull() ? null : v;
    }

    private static Instant parseTs(String s) {
        if (s == null || s.isBlank()) return null;
        // SQLite datetime('now') → "YYYY-MM-DD HH:MM:SS"; Instant.toString() → ISO-8601.
        try {
            return Instant.parse(s);
        } catch (Exception ignore) {
            return LocalDateTime.parse(s.replace(' ', 'T')).toInstant(ZoneOffset.UTC);
        }
    }

    private static String toText(Instant i) {
        return Timestamp.from(i).toString();
    }
}
```

- [ ] **Step 3.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.imaging.SequenceRepositoryTest'`
Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 3.5: Commit**

```bash
git add src/main/java/dev/nocs/imaging/SequenceRepository.java \
        src/test/java/dev/nocs/imaging/SequenceRepositoryTest.java
git commit -m "feat(imaging): SequenceRepository (insert/update/list)"
```

---

### Task 4: `nocs.imaging.*` config

**Files:**
- Modify: `src/main/java/dev/nocs/config/NocsProperties.java`
- Modify: `src/main/resources/application.yaml`
- Modify: `src/main/resources/config.example.yaml`
- Create: `src/test/java/dev/nocs/imaging/ImagingConfigTest.java`

- [ ] **Step 4.1: Write the failing test**

Create `src/test/java/dev/nocs/imaging/ImagingConfigTest.java`:

```java
package dev.nocs.imaging;

import dev.nocs.config.NocsProperties;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@TestPropertySource(properties = {
        "nocs.imaging.slew-settle-ms=2500",
        "nocs.imaging.sync-threshold-arcmin=2.0",
        "nocs.imaging.post-slew-solve-timeout-sec=45",
        "nocs.imaging.test-exposure-sec=1.5",
        "nocs.imaging.dither-settle-ms=2000",
        "nocs.imaging.image-await-timeout-ms=60000",
        "nocs.imaging.autofocus.strategy=noop"
})
class ImagingConfigTest {

    @Autowired
    NocsProperties props;

    @Test
    void binds() {
        assertThat(props.imaging()).isNotNull();
        assertThat(props.imaging().slewSettleMs()).isEqualTo(2500);
        assertThat(props.imaging().syncThresholdArcmin()).isEqualTo(2.0);
        assertThat(props.imaging().postSlewSolveTimeoutSec()).isEqualTo(45);
        assertThat(props.imaging().testExposureSec()).isEqualTo(1.5);
        assertThat(props.imaging().ditherSettleMs()).isEqualTo(2000);
        assertThat(props.imaging().imageAwaitTimeoutMs()).isEqualTo(60000);
        assertThat(props.imaging().autofocus().strategy()).isEqualTo("noop");
    }

    @Test
    void defaults() {
        // when nothing is overridden, Imaging must be non-null with sensible defaults
        NocsProperties.Imaging fresh = new NocsProperties.Imaging(null, null, null, null, null, null, null);
        assertThat(fresh.slewSettleMs()).isEqualTo(2000);
        assertThat(fresh.syncThresholdArcmin()).isEqualTo(1.0);
        assertThat(fresh.postSlewSolveTimeoutSec()).isEqualTo(30);
        assertThat(fresh.testExposureSec()).isEqualTo(2.0);
        assertThat(fresh.ditherSettleMs()).isEqualTo(2000);
        assertThat(fresh.imageAwaitTimeoutMs()).isEqualTo(30000);
        assertThat(fresh.autofocus().strategy()).isEqualTo("noop");
    }
}
```

- [ ] **Step 4.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.imaging.ImagingConfigTest'`
Expected: compile failure — `NocsProperties.Imaging` missing.

- [ ] **Step 4.3: Extend `NocsProperties`**

Replace the `record NocsProperties(...)` header and add the `Imaging` nested record. Apply the following edit in `src/main/java/dev/nocs/config/NocsProperties.java`.

Change the record header to include `imaging`:

```java
@ConfigurationProperties(prefix = "nocs")
public record NocsProperties(
        Auth auth,
        Server server,
        Datasource datasource,
        String dataDir,
        IndiConfig indi,
        Targets targets,
        Safety safety,
        PlateSolving platesolving,
        Imaging imaging) {
```

Add the following nested record inside `NocsProperties` (place it just before the closing brace, adjacent to the other records):

```java
    public record Imaging(
            Long slewSettleMs,
            Double syncThresholdArcmin,
            Long postSlewSolveTimeoutSec,
            Double testExposureSec,
            Long ditherSettleMs,
            Long imageAwaitTimeoutMs,
            Autofocus autofocus) {

        public Imaging {
            if (slewSettleMs == null || slewSettleMs < 0) slewSettleMs = 2000L;
            if (syncThresholdArcmin == null || syncThresholdArcmin < 0) syncThresholdArcmin = 1.0;
            if (postSlewSolveTimeoutSec == null || postSlewSolveTimeoutSec <= 0) postSlewSolveTimeoutSec = 30L;
            if (testExposureSec == null || testExposureSec <= 0) testExposureSec = 2.0;
            if (ditherSettleMs == null || ditherSettleMs < 0) ditherSettleMs = 2000L;
            if (imageAwaitTimeoutMs == null || imageAwaitTimeoutMs <= 0) imageAwaitTimeoutMs = 30_000L;
            if (autofocus == null) autofocus = new Autofocus(null);
        }

        public record Autofocus(String strategy) {
            public Autofocus {
                if (strategy == null || strategy.isBlank()) strategy = "noop";
            }
        }
    }
```

- [ ] **Step 4.4: Append defaults to `application.yaml`**

Append under `nocs:` in `src/main/resources/application.yaml`:

```yaml
  imaging:
    slew-settle-ms: 2000
    sync-threshold-arcmin: 1.0
    post-slew-solve-timeout-sec: 30
    test-exposure-sec: 2.0
    dither-settle-ms: 2000
    image-await-timeout-ms: 30000
    autofocus:
      strategy: noop
```

- [ ] **Step 4.5: Append an `imaging:` block to `config.example.yaml`**

Append to `src/main/resources/config.example.yaml` (after the `platesolving:` block, before the trailing `# Future sections:` comment):

```yaml
  # Imaging / sequence engine (Plan G).
  imaging:
    # Delay after the mount reports TRACKING before the slew_and_sync test exposure.
    slew-settle-ms: 2000
    # If the post-slew plate solve is further than this from the requested target,
    # issue mount.syncTo(ra, dec) and continue. Tighter threshold → more syncs.
    sync-threshold-arcmin: 1.0
    # Per-attempt timeout for the plate solve during slew_and_sync (seconds).
    post-slew-solve-timeout-sec: 30
    # Exposure length used for the slew_and_sync test frame (seconds).
    test-exposure-sec: 2.0
    # Wait after a dither slew completes before starting the next sub.
    dither-settle-ms: 2000
    # Max time to wait for a sub's CAMERA/image_saved event. Subs that exceed this
    # fail the step; the engine emits sub_failed and stops the sequence.
    image-await-timeout-ms: 30000
    autofocus:
      # noop = skip autofocus (seam for a v0.2 HFR-sweep implementation).
      strategy: noop
```

- [ ] **Step 4.6: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.imaging.ImagingConfigTest'`
Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 4.7: Commit**

```bash
git add src/main/java/dev/nocs/config/NocsProperties.java \
        src/main/resources/application.yaml \
        src/main/resources/config.example.yaml \
        src/test/java/dev/nocs/imaging/ImagingConfigTest.java
git commit -m "feat(imaging): nocs.imaging.* config block"
```

---

### Task 5: REST DTOs + JSON mapping

**Files:**
- Create: `src/main/java/dev/nocs/imaging/api/dto/DitherDto.java`
- Create: `src/main/java/dev/nocs/imaging/api/dto/PreStepDto.java`
- Create: `src/main/java/dev/nocs/imaging/api/dto/SequenceStepDto.java`
- Create: `src/main/java/dev/nocs/imaging/api/dto/DeviceIdsDto.java`
- Create: `src/main/java/dev/nocs/imaging/api/dto/SequenceDefinitionDto.java`
- Create: `src/main/java/dev/nocs/imaging/api/dto/SequenceView.java`
- Create: `src/main/java/dev/nocs/imaging/api/dto/AbortRequest.java`
- Create: `src/test/java/dev/nocs/imaging/api/SequenceDtoMappingTest.java`

- [ ] **Step 5.1: Write the failing test**

Create `src/test/java/dev/nocs/imaging/api/SequenceDtoMappingTest.java`:

```java
package dev.nocs.imaging.api;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.nocs.imaging.DitherOptions;
import dev.nocs.imaging.PreStep;
import dev.nocs.imaging.SequenceDefinition;
import dev.nocs.imaging.SequenceStep;
import dev.nocs.imaging.api.dto.SequenceDefinitionDto;
import java.util.List;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SequenceDtoMappingTest {

    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    void parseSpecExample() throws Exception {
        String json = """
                {
                  "target_id": "messier:M31",
                  "dither": { "enabled": true, "pixels": 10, "every_n_subs": 1 },
                  "pre_steps": [
                    { "type": "slew_and_sync" },
                    { "type": "autofocus" }
                  ],
                  "steps": [
                    { "filter": "L", "exposure_s": 120, "count": 30 },
                    { "filter": "R", "exposure_s": 180, "count": 10 }
                  ]
                }
                """;
        SequenceDefinitionDto dto = mapper.readValue(json, SequenceDefinitionDto.class);
        SequenceDefinition def = dto.toDomain();
        assertThat(def.targetId()).isEqualTo("messier:M31");
        assertThat(def.dither().enabled()).isTrue();
        assertThat(def.dither().pixels()).isEqualTo(10);
        assertThat(def.preSteps()).hasSize(2);
        assertThat(def.preSteps().get(0)).isInstanceOf(PreStep.SlewAndSyncStep.class);
        assertThat(def.steps()).hasSize(2);
        assertThat(def.steps().get(0).filter()).isEqualTo("L");
        assertThat(def.steps().get(0).exposureSec()).isEqualTo(120.0);
        assertThat(def.steps().get(0).count()).isEqualTo(30);
    }

    @Test
    void fromDomainRoundTrip() throws Exception {
        SequenceDefinition def = new SequenceDefinition(
                "ngc7000-oiii",
                "ngc:7000",
                new DitherOptions(true, 5, 2),
                List.of(new PreStep.SlewAndSyncStep()),
                List.of(new SequenceStep("O3", 300, 5, null)),
                null);
        SequenceDefinitionDto dto = SequenceDefinitionDto.fromDomain(def);
        String json = mapper.writeValueAsString(dto);
        SequenceDefinition parsed = mapper.readValue(json, SequenceDefinitionDto.class).toDomain();
        assertThat(parsed.name()).isEqualTo("ngc7000-oiii");
        assertThat(parsed.dither().everyNSubs()).isEqualTo(2);
        assertThat(parsed.steps().get(0).name()).isEqualTo("step-O3");
    }

    @Test
    void rejectUnknownPrestep() {
        String json = "{\"target_id\":\"messier:M31\",\"pre_steps\":[{\"type\":\"teleport\"}],\"steps\":[{\"filter\":\"L\",\"exposure_s\":1,\"count\":1}]}";
        org.assertj.core.api.Assertions.assertThatThrownBy(() -> mapper.readValue(json, SequenceDefinitionDto.class).toDomain())
                .hasMessageContaining("teleport");
    }
}
```

- [ ] **Step 5.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.imaging.api.SequenceDtoMappingTest'`
Expected: compile failure — DTOs missing.

- [ ] **Step 5.3: Implement DTOs**

Create `src/main/java/dev/nocs/imaging/api/dto/DitherDto.java`:

```java
package dev.nocs.imaging.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import dev.nocs.imaging.DitherOptions;

public record DitherDto(
        @JsonProperty("enabled") Boolean enabled,
        @JsonProperty("pixels") Integer pixels,
        @JsonProperty("every_n_subs") Integer everyNSubs) {

    public DitherOptions toDomain() {
        boolean on = Boolean.TRUE.equals(enabled);
        if (!on) return DitherOptions.disabled();
        int px = pixels == null ? 10 : pixels;
        int n = everyNSubs == null ? 1 : everyNSubs;
        return new DitherOptions(true, px, n);
    }

    public static DitherDto fromDomain(DitherOptions d) {
        return new DitherDto(d.enabled(), d.pixels(), d.everyNSubs());
    }
}
```

Create `src/main/java/dev/nocs/imaging/api/dto/PreStepDto.java`:

```java
package dev.nocs.imaging.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import dev.nocs.imaging.PreStep;

public record PreStepDto(@JsonProperty("type") String type) {

    public PreStep toDomain() {
        return PreStep.fromWire(type);
    }

    public static PreStepDto fromDomain(PreStep s) {
        return new PreStepDto(s.wire());
    }
}
```

Create `src/main/java/dev/nocs/imaging/api/dto/SequenceStepDto.java`:

```java
package dev.nocs.imaging.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import dev.nocs.imaging.SequenceStep;

public record SequenceStepDto(
        @JsonProperty("filter") String filter,
        @JsonProperty("exposure_s") Double exposureSec,
        @JsonProperty("count") Integer count,
        @JsonProperty("name") String name) {

    public SequenceStep toDomain() {
        double exp = exposureSec == null ? 0 : exposureSec;
        int c = count == null ? 1 : count;
        return new SequenceStep(filter, exp, c, name);
    }

    public static SequenceStepDto fromDomain(SequenceStep s) {
        return new SequenceStepDto(s.filter(), s.exposureSec(), s.count(), s.name());
    }
}
```

Create `src/main/java/dev/nocs/imaging/api/dto/DeviceIdsDto.java`:

```java
package dev.nocs.imaging.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import dev.nocs.imaging.SequenceDefinition;

public record DeviceIdsDto(
        @JsonProperty("mount_id") String mountId,
        @JsonProperty("camera_id") String cameraId,
        @JsonProperty("filter_wheel_id") String filterWheelId,
        @JsonProperty("focuser_id") String focuserId) {

    public SequenceDefinition.DeviceIds toDomain() {
        return new SequenceDefinition.DeviceIds(mountId, cameraId, filterWheelId, focuserId);
    }

    public static DeviceIdsDto fromDomain(SequenceDefinition.DeviceIds d) {
        if (d == null) return new DeviceIdsDto(null, null, null, null);
        return new DeviceIdsDto(d.mountId(), d.cameraId(), d.filterWheelId(), d.focuserId());
    }
}
```

Create `src/main/java/dev/nocs/imaging/api/dto/SequenceDefinitionDto.java`:

```java
package dev.nocs.imaging.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import dev.nocs.imaging.PreStep;
import dev.nocs.imaging.SequenceDefinition;
import dev.nocs.imaging.SequenceStep;
import java.util.List;

public record SequenceDefinitionDto(
        @JsonProperty("name") String name,
        @JsonProperty("target_id") String targetId,
        @JsonProperty("dither") DitherDto dither,
        @JsonProperty("pre_steps") List<PreStepDto> preSteps,
        @JsonProperty("steps") List<SequenceStepDto> steps,
        @JsonProperty("device_ids") DeviceIdsDto deviceIds) {

    public SequenceDefinition toDomain() {
        List<PreStep> ps = preSteps == null ? List.of() : preSteps.stream().map(PreStepDto::toDomain).toList();
        List<SequenceStep> st = steps == null ? List.of() : steps.stream().map(SequenceStepDto::toDomain).toList();
        return new SequenceDefinition(
                name,
                targetId,
                dither == null ? null : dither.toDomain(),
                ps,
                st,
                deviceIds == null ? null : deviceIds.toDomain());
    }

    public static SequenceDefinitionDto fromDomain(SequenceDefinition d) {
        return new SequenceDefinitionDto(
                d.name(),
                d.targetId(),
                DitherDto.fromDomain(d.dither()),
                d.preSteps().stream().map(PreStepDto::fromDomain).toList(),
                d.steps().stream().map(SequenceStepDto::fromDomain).toList(),
                DeviceIdsDto.fromDomain(d.deviceIds()));
    }
}
```

Create `src/main/java/dev/nocs/imaging/api/dto/SequenceView.java`:

```java
package dev.nocs.imaging.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.nocs.imaging.SequenceRun;
import dev.nocs.imaging.SequenceStatus;
import java.time.Instant;

public record SequenceView(
        @JsonProperty("id") long id,
        @JsonProperty("session_id") Long sessionId,
        @JsonProperty("name") String name,
        @JsonProperty("status") String status,
        @JsonProperty("failure_reason") String failureReason,
        @JsonProperty("created_at") Instant createdAt,
        @JsonProperty("started_at") Instant startedAt,
        @JsonProperty("finished_at") Instant finishedAt,
        @JsonProperty("current_step_index") Integer currentStepIndex,
        @JsonProperty("current_sub_index") Integer currentSubIndex,
        @JsonProperty("subs_completed") int subsCompleted,
        @JsonProperty("subs_total") int subsTotal,
        @JsonProperty("definition") SequenceDefinitionDto definition) {

    public static SequenceView from(SequenceRun r, ObjectMapper mapper) {
        SequenceDefinitionDto def = null;
        try {
            def = mapper.readValue(r.definitionJson(), SequenceDefinitionDto.class);
        } catch (Exception ignored) {
            // surface the raw JSON in a degraded view rather than 500
        }
        return new SequenceView(
                r.id(), r.sessionId(), r.name(),
                (r.status() == null ? SequenceStatus.PENDING : r.status()).wire(),
                r.failureReason(),
                r.createdAt(), r.startedAt(), r.finishedAt(),
                r.currentStepIndex(), r.currentSubIndex(),
                r.subsCompleted(), r.subsTotal(),
                def);
    }
}
```

Create `src/main/java/dev/nocs/imaging/api/dto/AbortRequest.java`:

```java
package dev.nocs.imaging.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

public record AbortRequest(@JsonProperty("reason") String reason) {}
```

- [ ] **Step 5.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.imaging.api.SequenceDtoMappingTest'`
Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 5.5: Commit**

```bash
git add src/main/java/dev/nocs/imaging/api/dto/ \
        src/test/java/dev/nocs/imaging/api/SequenceDtoMappingTest.java
git commit -m "feat(imaging): REST DTOs + JSON mapping for sequences"
```

---

### Task 6: `ImageAwait` helper

**Files:**
- Create: `src/main/java/dev/nocs/imaging/ImageAwait.java`
- Create: `src/test/java/dev/nocs/imaging/ImageAwaitTest.java`

The helper subscribes to `Topic.CAMERA / image_saved` events and hands back a `CompletableFuture<Long>` (the saved image id) that completes when a matching event arrives, or completes exceptionally on timeout.

- [ ] **Step 6.1: Write the failing test**

Create `src/test/java/dev/nocs/imaging/ImageAwaitTest.java`:

```java
package dev.nocs.imaging;

import dev.nocs.device.DeviceId;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class ImageAwaitTest {

    @Test
    void matchesByCameraStepSeqAndTarget() throws Exception {
        EventBus bus = new EventBus();
        ImageAwait await = new ImageAwait(bus);
        CompletableFuture<Long> f = await.waitFor(
                new DeviceId("cam-1"), "m31", "step-L", 3, Duration.ofSeconds(2));

        bus.publish(Event.of(Topic.CAMERA, "image_saved", Map.of(
                "id", 99L, "device", "cam-2", "step", "step-L", "seq", 3, "target", "m31")));
        bus.publish(Event.of(Topic.CAMERA, "image_saved", Map.of(
                "id", 100L, "device", "cam-1", "step", "step-L", "seq", 2, "target", "m31")));
        bus.publish(Event.of(Topic.CAMERA, "image_saved", Map.of(
                "id", 101L, "device", "cam-1", "step", "step-L", "seq", 3, "target", "m31")));

        assertThat(f.get(2, TimeUnit.SECONDS)).isEqualTo(101L);
    }

    @Test
    void timesOut() {
        EventBus bus = new EventBus();
        ImageAwait await = new ImageAwait(bus);
        CompletableFuture<Long> f = await.waitFor(
                new DeviceId("cam-1"), "m31", "step-L", 1, Duration.ofMillis(200));
        assertThatThrownBy(() -> f.get(1, TimeUnit.SECONDS))
                .isInstanceOf(ExecutionException.class)
                .hasRootCauseInstanceOf(TimeoutException.class);
    }

    @Test
    void ignoresWrongTopic() throws Exception {
        EventBus bus = new EventBus();
        ImageAwait await = new ImageAwait(bus);
        CompletableFuture<Long> f = await.waitFor(
                new DeviceId("cam-1"), "m31", "step-L", 1, Duration.ofSeconds(2));
        bus.publish(Event.of(Topic.CAMERA, "image_received", Map.of(
                "id", 1L, "device", "cam-1", "step", "step-L", "seq", 1, "target", "m31")));
        bus.publish(Event.of(Topic.CAMERA, "image_saved", Map.of(
                "id", 2L, "device", "cam-1", "step", "step-L", "seq", 1, "target", "m31")));
        assertThat(f.get(2, TimeUnit.SECONDS)).isEqualTo(2L);
    }
}
```

- [ ] **Step 6.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.imaging.ImageAwaitTest'`
Expected: compile failure — `ImageAwait` missing.

- [ ] **Step 6.3: Implement `ImageAwait`**

Create `src/main/java/dev/nocs/imaging/ImageAwait.java`:

```java
package dev.nocs.imaging;

import dev.nocs.device.DeviceId;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import java.time.Duration;
import java.util.EnumSet;
import java.util.Objects;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import org.springframework.stereotype.Component;
import reactor.core.Disposable;

@Component
public class ImageAwait {

    private final EventBus bus;
    private final ScheduledExecutorService timers =
            Executors.newSingleThreadScheduledExecutor(r -> {
                Thread t = new Thread(r, "image-await-timer");
                t.setDaemon(true);
                return t;
            });

    public ImageAwait(EventBus bus) {
        this.bus = bus;
    }

    public CompletableFuture<Long> waitFor(DeviceId camera, String target, String step, int seq, Duration timeout) {
        CompletableFuture<Long> fut = new CompletableFuture<>();
        Disposable sub = bus.subscribe(EnumSet.of(Topic.CAMERA)).subscribe(event -> {
            if (!"image_saved".equals(event.type())) return;
            if (!matches(event, camera, target, step, seq)) return;
            Object idObj = event.payload().get("id");
            if (idObj instanceof Number n) {
                fut.complete(n.longValue());
            } else {
                fut.complete(-1L);
            }
        });
        var deadline = timers.schedule(
                () -> fut.completeExceptionally(new TimeoutException("timed out waiting for image_saved")),
                timeout.toMillis(),
                TimeUnit.MILLISECONDS);
        fut.whenComplete((v, e) -> {
            sub.dispose();
            deadline.cancel(false);
        });
        return fut;
    }

    private static boolean matches(Event event, DeviceId camera, String target, String step, int seq) {
        Object dev = event.payload().get("device");
        Object tgt = event.payload().get("target");
        Object stp = event.payload().get("step");
        Object sq = event.payload().get("seq");
        if (!Objects.equals(dev, camera.value())) return false;
        if (!Objects.equals(tgt, target)) return false;
        if (!Objects.equals(stp, step)) return false;
        if (!(sq instanceof Number n) || n.intValue() != seq) return false;
        return true;
    }
}
```

- [ ] **Step 6.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.imaging.ImageAwaitTest'`
Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 6.5: Commit**

```bash
git add src/main/java/dev/nocs/imaging/ImageAwait.java \
        src/test/java/dev/nocs/imaging/ImageAwaitTest.java
git commit -m "feat(imaging): ImageAwait helper (correlates CAMERA/image_saved to a sub)"
```

---

### Task 7: `DeviceSelector` + `SequenceSetupException`

**Files:**
- Create: `src/main/java/dev/nocs/imaging/SequenceSetupException.java`
- Create: `src/main/java/dev/nocs/imaging/DeviceSelector.java`
- Create: `src/test/java/dev/nocs/imaging/DeviceSelectorTest.java`

- [ ] **Step 7.1: Write the failing test**

Create `src/test/java/dev/nocs/imaging/DeviceSelectorTest.java`:

```java
package dev.nocs.imaging;

import dev.nocs.device.Camera;
import dev.nocs.device.CameraState;
import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceKind;
import dev.nocs.device.DeviceRegistry;
import dev.nocs.device.FilterWheel;
import dev.nocs.device.FilterWheelState;
import dev.nocs.device.Focuser;
import dev.nocs.device.FocuserState;
import dev.nocs.device.Mount;
import dev.nocs.device.MountState;
import java.util.List;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class DeviceSelectorTest {

    @Test
    void picksSingleConnectedDeviceOfEachKind() {
        DeviceRegistry reg = new DeviceRegistry();
        FakeMount m = new FakeMount("m");
        FakeCamera c = new FakeCamera("c");
        FakeWheel w = new FakeWheel("w");
        FakeFocuser f = new FakeFocuser("f");
        m.connect(); c.connect(); w.connect(); f.connect();
        reg.add(m); reg.add(c); reg.add(w); reg.add(f);

        DeviceSelector sel = new DeviceSelector(reg);
        var r = sel.resolve(SequenceDefinition.DeviceIds.empty());
        assertThat(r.mount()).isSameAs(m);
        assertThat(r.camera()).isSameAs(c);
        assertThat(r.filterWheel()).isSameAs(w);
        assertThat(r.focuser()).isSameAs(f);
    }

    @Test
    void explicitIdsWin() {
        DeviceRegistry reg = new DeviceRegistry();
        FakeMount m1 = new FakeMount("m1"); m1.connect();
        FakeMount m2 = new FakeMount("m2"); m2.connect();
        FakeCamera c = new FakeCamera("c"); c.connect();
        FakeWheel w = new FakeWheel("w"); w.connect();
        FakeFocuser f = new FakeFocuser("f"); f.connect();
        reg.add(m1); reg.add(m2); reg.add(c); reg.add(w); reg.add(f);

        DeviceSelector sel = new DeviceSelector(reg);
        var r = sel.resolve(new SequenceDefinition.DeviceIds("m2", null, null, null));
        assertThat(r.mount()).isSameAs(m2);
    }

    @Test
    void ambiguousThrows() {
        DeviceRegistry reg = new DeviceRegistry();
        FakeMount m1 = new FakeMount("m1"); m1.connect();
        FakeMount m2 = new FakeMount("m2"); m2.connect();
        reg.add(m1); reg.add(m2);

        DeviceSelector sel = new DeviceSelector(reg);
        assertThatThrownBy(() -> sel.resolve(SequenceDefinition.DeviceIds.empty()))
                .isInstanceOf(SequenceSetupException.class)
                .hasMessageContaining("multiple");
    }

    @Test
    void unconnectedThrows() {
        DeviceRegistry reg = new DeviceRegistry();
        FakeMount m = new FakeMount("m"); // not connected
        reg.add(m);
        DeviceSelector sel = new DeviceSelector(reg);
        assertThatThrownBy(() -> sel.resolve(SequenceDefinition.DeviceIds.empty()))
                .isInstanceOf(SequenceSetupException.class)
                .hasMessageContaining("not connected");
    }

    @Test
    void missingRequiredKindThrows() {
        DeviceRegistry reg = new DeviceRegistry();
        FakeCamera c = new FakeCamera("c"); c.connect();
        reg.add(c);
        DeviceSelector sel = new DeviceSelector(reg);
        assertThatThrownBy(() -> sel.resolve(SequenceDefinition.DeviceIds.empty()))
                .isInstanceOf(SequenceSetupException.class)
                .hasMessageContaining("mount");
    }

    // --- fakes ---

    private static final class FakeMount implements Mount {
        private final DeviceId id;
        private MountState s = MountState.DISCONNECTED;
        FakeMount(String id) { this.id = new DeviceId(id); }
        public DeviceId id() { return id; }
        public String indiName() { return id.value(); }
        public DeviceKind kind() { return DeviceKind.MOUNT; }
        public boolean isConnected() { return s != MountState.DISCONNECTED; }
        public void connect() { s = MountState.IDLE; }
        public void disconnect() { s = MountState.DISCONNECTED; }
        public MountState state() { return s; }
        public void slew(double r, double d) {}
        public void syncTo(double r, double d) {}
        public void park() {}
        public void unpark() {}
        public void abort() {}
    }

    private static final class FakeCamera implements Camera {
        private final DeviceId id;
        private CameraState s = CameraState.DISCONNECTED;
        FakeCamera(String id) { this.id = new DeviceId(id); }
        public DeviceId id() { return id; }
        public String indiName() { return id.value(); }
        public DeviceKind kind() { return DeviceKind.CAMERA; }
        public boolean isConnected() { return s != CameraState.DISCONNECTED; }
        public void connect() { s = CameraState.IDLE; }
        public void disconnect() { s = CameraState.DISCONNECTED; }
        public CameraState state() { return s; }
        public void cool(double x) {}
        public void expose(double x) {}
        public void abortExposure() {}
        public Double currentTemperatureCelsius() { return null; }
    }

    private static final class FakeWheel implements FilterWheel {
        private final DeviceId id;
        private FilterWheelState s = FilterWheelState.DISCONNECTED;
        FakeWheel(String id) { this.id = new DeviceId(id); }
        public DeviceId id() { return id; }
        public String indiName() { return id.value(); }
        public DeviceKind kind() { return DeviceKind.FILTERWHEEL; }
        public boolean isConnected() { return s != FilterWheelState.DISCONNECTED; }
        public void connect() { s = FilterWheelState.IDLE; }
        public void disconnect() { s = FilterWheelState.DISCONNECTED; }
        public FilterWheelState state() { return s; }
        public List<String> slotNames() { return List.of("L", "R", "G", "B"); }
        public int currentSlot() { return 1; }
        public void selectSlot(int slot) {}
    }

    private static final class FakeFocuser implements Focuser {
        private final DeviceId id;
        private FocuserState s = FocuserState.DISCONNECTED;
        FakeFocuser(String id) { this.id = new DeviceId(id); }
        public DeviceId id() { return id; }
        public String indiName() { return id.value(); }
        public DeviceKind kind() { return DeviceKind.FOCUSER; }
        public boolean isConnected() { return s != FocuserState.DISCONNECTED; }
        public void connect() { s = FocuserState.IDLE; }
        public void disconnect() { s = FocuserState.DISCONNECTED; }
        public FocuserState state() { return s; }
        public int currentPosition() { return 25_000; }
        public void moveAbsolute(int pos) {}
        public void moveRelative(int d) {}
        public void abort() {}
    }
}
```

- [ ] **Step 7.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.imaging.DeviceSelectorTest'`
Expected: compile failure — classes missing.

- [ ] **Step 7.3: Implement `SequenceSetupException`**

Create `src/main/java/dev/nocs/imaging/SequenceSetupException.java`:

```java
package dev.nocs.imaging;

public class SequenceSetupException extends RuntimeException {

    public enum Kind {
        MISSING_DEVICE,
        MULTIPLE_DEVICES,
        DEVICE_NOT_CONNECTED,
        TARGET_NOT_FOUND,
        TARGET_UNRESOLVABLE,
        INVALID_DEFINITION
    }

    private final Kind kind;

    public SequenceSetupException(Kind kind, String message) {
        super(message);
        this.kind = kind;
    }

    public Kind kind() {
        return kind;
    }
}
```

- [ ] **Step 7.4: Implement `DeviceSelector`**

Create `src/main/java/dev/nocs/imaging/DeviceSelector.java`:

```java
package dev.nocs.imaging;

import dev.nocs.device.Camera;
import dev.nocs.device.Device;
import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceKind;
import dev.nocs.device.DeviceRegistry;
import dev.nocs.device.FilterWheel;
import dev.nocs.device.Focuser;
import dev.nocs.device.Mount;
import java.util.List;
import java.util.Optional;
import java.util.function.Function;
import org.springframework.stereotype.Component;

@Component
public class DeviceSelector {

    private final DeviceRegistry registry;

    public DeviceSelector(DeviceRegistry registry) {
        this.registry = registry;
    }

    public Resolved resolve(SequenceDefinition.DeviceIds pinned) {
        Mount m = pickConnected(
                DeviceKind.MOUNT, "mount",
                pinned == null ? null : pinned.mountId(),
                id -> registry.mount(id).map(x -> (Device) x));
        Camera c = pickConnected(
                DeviceKind.CAMERA, "camera",
                pinned == null ? null : pinned.cameraId(),
                id -> registry.camera(id).map(x -> (Device) x));
        FilterWheel w = pickConnected(
                DeviceKind.FILTERWHEEL, "filter wheel",
                pinned == null ? null : pinned.filterWheelId(),
                id -> registry.filterWheel(id).map(x -> (Device) x));
        Focuser f = pickConnected(
                DeviceKind.FOCUSER, "focuser",
                pinned == null ? null : pinned.focuserId(),
                id -> registry.focuser(id).map(x -> (Device) x));
        return new Resolved(m, c, w, f);
    }

    @SuppressWarnings("unchecked")
    private <T extends Device> T pickConnected(
            DeviceKind kind, String label, String pinnedId, Function<DeviceId, Optional<Device>> lookup) {
        if (pinnedId != null && !pinnedId.isBlank()) {
            Device d = lookup.apply(new DeviceId(pinnedId))
                    .orElseThrow(() -> new SequenceSetupException(
                            SequenceSetupException.Kind.MISSING_DEVICE,
                            "no " + label + " with id " + pinnedId));
            if (!d.isConnected()) {
                throw new SequenceSetupException(
                        SequenceSetupException.Kind.DEVICE_NOT_CONNECTED,
                        label + " " + pinnedId + " is not connected");
            }
            return (T) d;
        }
        List<Device> candidates = registry.all().stream()
                .filter(d -> d.kind() == kind)
                .toList();
        List<Device> connected = candidates.stream().filter(Device::isConnected).toList();
        if (connected.isEmpty()) {
            if (candidates.isEmpty()) {
                throw new SequenceSetupException(
                        SequenceSetupException.Kind.MISSING_DEVICE,
                        "no " + label + " available (required for this sequence)");
            }
            throw new SequenceSetupException(
                    SequenceSetupException.Kind.DEVICE_NOT_CONNECTED,
                    label + " is not connected (" + candidates.size() + " available)");
        }
        if (connected.size() > 1) {
            throw new SequenceSetupException(
                    SequenceSetupException.Kind.MULTIPLE_DEVICES,
                    "multiple connected " + label + "s; pin one via device_ids." + idField(kind));
        }
        return (T) connected.get(0);
    }

    private static String idField(DeviceKind k) {
        return switch (k) {
            case MOUNT -> "mount_id";
            case CAMERA -> "camera_id";
            case FILTERWHEEL -> "filter_wheel_id";
            case FOCUSER -> "focuser_id";
        };
    }

    public record Resolved(Mount mount, Camera camera, FilterWheel filterWheel, Focuser focuser) {}
}
```

- [ ] **Step 7.5: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.imaging.DeviceSelectorTest'`
Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 7.6: Commit**

```bash
git add src/main/java/dev/nocs/imaging/DeviceSelector.java \
        src/main/java/dev/nocs/imaging/SequenceSetupException.java \
        src/test/java/dev/nocs/imaging/DeviceSelectorTest.java
git commit -m "feat(imaging): DeviceSelector (single-connected / pinned) + setup exception"
```

---

### Task 8: `DitherStrategy` + `PixelOffsetDitherStrategy`

**Files:**
- Create: `src/main/java/dev/nocs/imaging/DitherStrategy.java`
- Create: `src/main/java/dev/nocs/imaging/PixelOffsetDitherStrategy.java`
- Create: `src/test/java/dev/nocs/imaging/PixelOffsetDitherStrategyTest.java`

The strategy takes a last known `PlateSolution` (for pixel scale), a mount, the current RA/Dec, and a pixel offset magnitude; it chooses a pseudo-random direction based on a seed (so tests are deterministic) and issues `mount.slew(...)`.

- [ ] **Step 8.1: Write the failing test**

Create `src/test/java/dev/nocs/imaging/PixelOffsetDitherStrategyTest.java`:

```java
package dev.nocs.imaging;

import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceKind;
import dev.nocs.device.Mount;
import dev.nocs.device.MountState;
import dev.nocs.platesolving.PlateSolution;
import java.time.Instant;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class PixelOffsetDitherStrategyTest {

    @Test
    void skipsWithoutSolution() {
        FakeMount m = new FakeMount();
        PixelOffsetDitherStrategy s = new PixelOffsetDitherStrategy(42L);
        DitherStrategy.DitherResult r = s.dither(m, null, 12.0, 40.0, 10, 0);
        assertThat(r.skipped()).isTrue();
        assertThat(m.slewCalls).isZero();
    }

    @Test
    void computesBoundedOffsetAndSlews() {
        FakeMount m = new FakeMount();
        PlateSolution sol = new PlateSolution(180.0, 40.0, 1.5, 0, 1, 1, Instant.now(), "fake");
        PixelOffsetDitherStrategy s = new PixelOffsetDitherStrategy(42L);
        DitherStrategy.DitherResult r = s.dither(m, sol, 12.0, 40.0, 10, 0);
        assertThat(r.skipped()).isFalse();
        assertThat(m.slewCalls).isEqualTo(1);
        // With pixelScale=1.5"/px and offset=10px → up to ±15" ≈ ±0.00416 deg.
        assertThat(Math.abs(r.newRaHours() - 12.0) * 15.0).isLessThan(0.02);
        assertThat(Math.abs(r.newDecDeg() - 40.0)).isLessThan(0.02);
    }

    @Test
    void deterministicForSameSeed() {
        PlateSolution sol = new PlateSolution(180.0, 40.0, 1.5, 0, 1, 1, Instant.now(), "fake");
        DitherStrategy.DitherResult r1 = new PixelOffsetDitherStrategy(7L).dither(new FakeMount(), sol, 12.0, 40.0, 10, 0);
        DitherStrategy.DitherResult r2 = new PixelOffsetDitherStrategy(7L).dither(new FakeMount(), sol, 12.0, 40.0, 10, 0);
        assertThat(r1.newRaHours()).isEqualTo(r2.newRaHours());
        assertThat(r1.newDecDeg()).isEqualTo(r2.newDecDeg());
    }

    private static final class FakeMount implements Mount {
        int slewCalls;
        private MountState s = MountState.TRACKING;
        public DeviceId id() { return new DeviceId("fake-mount"); }
        public String indiName() { return "fake-mount"; }
        public DeviceKind kind() { return DeviceKind.MOUNT; }
        public boolean isConnected() { return s != MountState.DISCONNECTED; }
        public void connect() { s = MountState.IDLE; }
        public void disconnect() { s = MountState.DISCONNECTED; }
        public MountState state() { return s; }
        public void slew(double r, double d) { slewCalls++; }
        public void syncTo(double r, double d) {}
        public void park() {}
        public void unpark() {}
        public void abort() {}
    }
}
```

- [ ] **Step 8.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.imaging.PixelOffsetDitherStrategyTest'`
Expected: compile failure.

- [ ] **Step 8.3: Implement `DitherStrategy`**

Create `src/main/java/dev/nocs/imaging/DitherStrategy.java`:

```java
package dev.nocs.imaging;

import dev.nocs.device.Mount;
import dev.nocs.platesolving.PlateSolution;

public interface DitherStrategy {

    DitherResult dither(
            Mount mount,
            PlateSolution lastSolution,
            double currentRaHours,
            double currentDecDeg,
            int pixelOffset,
            long settleMs);

    record DitherResult(
            double newRaHours,
            double newDecDeg,
            boolean skipped,
            String skipReason) {}
}
```

- [ ] **Step 8.4: Implement `PixelOffsetDitherStrategy`**

Create `src/main/java/dev/nocs/imaging/PixelOffsetDitherStrategy.java`:

```java
package dev.nocs.imaging;

import dev.nocs.device.Mount;
import dev.nocs.platesolving.PlateSolution;
import java.util.Random;

public class PixelOffsetDitherStrategy implements DitherStrategy {

    private final Random rng;

    public PixelOffsetDitherStrategy() {
        this(System.nanoTime());
    }

    public PixelOffsetDitherStrategy(long seed) {
        this.rng = new Random(seed);
    }

    @Override
    public DitherResult dither(
            Mount mount,
            PlateSolution lastSolution,
            double currentRaHours,
            double currentDecDeg,
            int pixelOffset,
            long settleMs) {
        if (lastSolution == null) {
            return new DitherResult(currentRaHours, currentDecDeg, true, "no_plate_solution");
        }
        if (pixelOffset <= 0) {
            return new DitherResult(currentRaHours, currentDecDeg, true, "offset_nonpositive");
        }
        double arcsecOffset = pixelOffset * Math.max(0.1, lastSolution.pixelScaleArcsecPerPx());
        double degOffset = arcsecOffset / 3600.0;

        // Pick a random direction on the unit circle.
        double theta = rng.nextDouble() * 2 * Math.PI;
        double deltaDec = degOffset * Math.sin(theta);
        double cosDec = Math.max(0.05, Math.cos(Math.toRadians(currentDecDeg)));
        double deltaRaDeg = (degOffset * Math.cos(theta)) / cosDec;

        double newDec = clampDec(currentDecDeg + deltaDec);
        double newRaHours = wrapRaHours(currentRaHours + deltaRaDeg / 15.0);

        mount.slew(newRaHours, newDec);
        if (settleMs > 0) {
            try {
                Thread.sleep(settleMs);
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
            }
        }
        return new DitherResult(newRaHours, newDec, false, null);
    }

    private static double clampDec(double dec) {
        if (dec > 89.9) return 89.9;
        if (dec < -89.9) return -89.9;
        return dec;
    }

    private static double wrapRaHours(double h) {
        double r = h % 24.0;
        if (r < 0) r += 24.0;
        return r;
    }
}
```

- [ ] **Step 8.5: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.imaging.PixelOffsetDitherStrategyTest'`
Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 8.6: Commit**

```bash
git add src/main/java/dev/nocs/imaging/DitherStrategy.java \
        src/main/java/dev/nocs/imaging/PixelOffsetDitherStrategy.java \
        src/test/java/dev/nocs/imaging/PixelOffsetDitherStrategyTest.java
git commit -m "feat(imaging): DitherStrategy + PixelOffsetDitherStrategy (no guider feedback)"
```

---

### Task 9: `AutofocusStrategy` + `NoopAutofocusStrategy`

**Files:**
- Create: `src/main/java/dev/nocs/imaging/AutofocusStrategy.java`
- Create: `src/main/java/dev/nocs/imaging/NoopAutofocusStrategy.java`
- Create: `src/test/java/dev/nocs/imaging/NoopAutofocusStrategyTest.java`

- [ ] **Step 9.1: Write the failing test**

Create `src/test/java/dev/nocs/imaging/NoopAutofocusStrategyTest.java`:

```java
package dev.nocs.imaging;

import dev.nocs.device.Camera;
import dev.nocs.device.CameraState;
import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceKind;
import dev.nocs.device.Focuser;
import dev.nocs.device.FocuserState;
import java.time.Instant;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class NoopAutofocusStrategyTest {

    @Test
    void returnsCurrentPosition() {
        FakeFocuser f = new FakeFocuser();
        FakeCamera c = new FakeCamera();
        NoopAutofocusStrategy s = new NoopAutofocusStrategy();
        var r = s.run(f, c, new AutofocusStrategy.AutofocusContext("messier:M31", Instant.now()));
        assertThat(r.bestPosition()).isEqualTo(25_000);
        assertThat(r.pointsTried()).isZero();
        assertThat(f.moves).isZero();
        assertThat(c.exposures).isZero();
    }

    private static final class FakeFocuser implements Focuser {
        int moves;
        public DeviceId id() { return new DeviceId("f"); }
        public String indiName() { return "f"; }
        public DeviceKind kind() { return DeviceKind.FOCUSER; }
        public boolean isConnected() { return true; }
        public void connect() {}
        public void disconnect() {}
        public FocuserState state() { return FocuserState.IDLE; }
        public int currentPosition() { return 25_000; }
        public void moveAbsolute(int p) { moves++; }
        public void moveRelative(int d) { moves++; }
        public void abort() {}
    }

    private static final class FakeCamera implements Camera {
        int exposures;
        public DeviceId id() { return new DeviceId("c"); }
        public String indiName() { return "c"; }
        public DeviceKind kind() { return DeviceKind.CAMERA; }
        public boolean isConnected() { return true; }
        public void connect() {}
        public void disconnect() {}
        public CameraState state() { return CameraState.IDLE; }
        public void cool(double x) {}
        public void expose(double x) { exposures++; }
        public void abortExposure() {}
        public Double currentTemperatureCelsius() { return null; }
    }
}
```

- [ ] **Step 9.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.imaging.NoopAutofocusStrategyTest'`
Expected: compile failure.

- [ ] **Step 9.3: Implement `AutofocusStrategy`**

Create `src/main/java/dev/nocs/imaging/AutofocusStrategy.java`:

```java
package dev.nocs.imaging;

import dev.nocs.device.Camera;
import dev.nocs.device.Focuser;
import java.time.Instant;

public interface AutofocusStrategy {

    AutofocusResult run(Focuser focuser, Camera camera, AutofocusContext ctx);

    record AutofocusResult(int bestPosition, int pointsTried, long durationMs) {}

    record AutofocusContext(String target, Instant at) {}
}
```

- [ ] **Step 9.4: Implement `NoopAutofocusStrategy`**

Create `src/main/java/dev/nocs/imaging/NoopAutofocusStrategy.java`:

```java
package dev.nocs.imaging;

import dev.nocs.device.Camera;
import dev.nocs.device.Focuser;

/**
 * v0.1 default: does not touch the focuser. The AutofocusStrategy interface is the seam
 * for a real hill-climb HFR-sweep implementation planned for v0.2.
 */
public class NoopAutofocusStrategy implements AutofocusStrategy {

    @Override
    public AutofocusResult run(Focuser focuser, Camera camera, AutofocusContext ctx) {
        return new AutofocusResult(focuser.currentPosition(), 0, 0L);
    }
}
```

- [ ] **Step 9.5: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.imaging.NoopAutofocusStrategyTest'`
Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 9.6: Commit**

```bash
git add src/main/java/dev/nocs/imaging/AutofocusStrategy.java \
        src/main/java/dev/nocs/imaging/NoopAutofocusStrategy.java \
        src/test/java/dev/nocs/imaging/NoopAutofocusStrategyTest.java
git commit -m "feat(imaging): AutofocusStrategy interface + NoopAutofocusStrategy (v0.1 default)"
```

---

### Task 10: `PauseAbortLatch`

**Files:**
- Create: `src/main/java/dev/nocs/imaging/PauseAbortLatch.java`
- Create: `src/test/java/dev/nocs/imaging/PauseAbortLatchTest.java`

- [ ] **Step 10.1: Write the failing test**

Create `src/test/java/dev/nocs/imaging/PauseAbortLatchTest.java`:

```java
package dev.nocs.imaging;

import java.time.Duration;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class PauseAbortLatchTest {

    @Test
    void awaitReturnsImmediatelyWhenNotPaused() throws Exception {
        PauseAbortLatch l = new PauseAbortLatch();
        l.awaitIfPaused(Duration.ofMillis(50));
        assertThat(l.isAbortRequested()).isFalse();
        assertThat(l.abortReason()).isNull();
    }

    @Test
    void blocksUntilResumed() throws Exception {
        PauseAbortLatch l = new PauseAbortLatch();
        l.pause();
        CountDownLatch started = new CountDownLatch(1);
        AtomicBoolean released = new AtomicBoolean(false);
        Thread t = Thread.ofVirtual().start(() -> {
            started.countDown();
            try {
                l.awaitIfPaused(Duration.ofSeconds(2));
                released.set(true);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        });
        assertThat(started.await(1, TimeUnit.SECONDS)).isTrue();
        Thread.sleep(50);
        assertThat(released.get()).isFalse();
        l.resume();
        t.join(1000);
        assertThat(released.get()).isTrue();
    }

    @Test
    void abortShortCircuitsPause() throws Exception {
        PauseAbortLatch l = new PauseAbortLatch();
        l.pause();
        CountDownLatch started = new CountDownLatch(1);
        AtomicBoolean released = new AtomicBoolean(false);
        Thread t = Thread.ofVirtual().start(() -> {
            started.countDown();
            try {
                l.awaitIfPaused(Duration.ofSeconds(2));
                released.set(true);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        });
        assertThat(started.await(1, TimeUnit.SECONDS)).isTrue();
        Thread.sleep(50);
        l.abort("e_stop");
        t.join(1000);
        assertThat(released.get()).isTrue();
        assertThat(l.isAbortRequested()).isTrue();
        assertThat(l.abortReason()).isEqualTo("e_stop");
    }
}
```

- [ ] **Step 10.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.imaging.PauseAbortLatchTest'`
Expected: compile failure.

- [ ] **Step 10.3: Implement `PauseAbortLatch`**

Create `src/main/java/dev/nocs/imaging/PauseAbortLatch.java`:

```java
package dev.nocs.imaging;

import java.time.Duration;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.locks.Condition;
import java.util.concurrent.locks.ReentrantLock;

public class PauseAbortLatch {

    private final ReentrantLock lock = new ReentrantLock();
    private final Condition cond = lock.newCondition();
    private boolean paused;
    private final AtomicReference<String> abortReason = new AtomicReference<>();

    public void pause() {
        lock.lock();
        try {
            paused = true;
        } finally {
            lock.unlock();
        }
    }

    public void resume() {
        lock.lock();
        try {
            paused = false;
            cond.signalAll();
        } finally {
            lock.unlock();
        }
    }

    public void abort(String reason) {
        abortReason.compareAndSet(null, reason == null ? "" : reason);
        lock.lock();
        try {
            paused = false;
            cond.signalAll();
        } finally {
            lock.unlock();
        }
    }

    public boolean isAbortRequested() {
        return abortReason.get() != null;
    }

    public String abortReason() {
        return abortReason.get();
    }

    public boolean isPaused() {
        lock.lock();
        try {
            return paused;
        } finally {
            lock.unlock();
        }
    }

    public void awaitIfPaused(Duration maxWait) throws InterruptedException {
        long deadline = System.nanoTime() + maxWait.toNanos();
        lock.lock();
        try {
            while (paused && !isAbortRequested()) {
                long remaining = deadline - System.nanoTime();
                if (remaining <= 0) return;
                cond.awaitNanos(remaining);
            }
        } finally {
            lock.unlock();
        }
    }
}
```

- [ ] **Step 10.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.imaging.PauseAbortLatchTest'`
Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 10.5: Commit**

```bash
git add src/main/java/dev/nocs/imaging/PauseAbortLatch.java \
        src/test/java/dev/nocs/imaging/PauseAbortLatchTest.java
git commit -m "feat(imaging): PauseAbortLatch (pause/resume/abort coordination)"
```

---

### Task 11: `SlewAndSync` pre-step helper

**Files:**
- Create: `src/main/java/dev/nocs/imaging/SlewAndSync.java`
- Create: `src/test/java/dev/nocs/imaging/SlewAndSyncTest.java`

`SlewAndSync` orchestrates the `slew_and_sync` pre-step: issue `mount.slew(ra, dec)` → await `MOUNT/state_changed → TRACKING` (via `DeviceAwait` inline helper) or a hardcoded settle → prepare a test-expose capture context → `camera.expose(testExposureSec)` → `ImageAwait` for the saved FITS → call `PlateSolvingService.solve(bytes, options)` → compare to the target; if offset > threshold, `mount.syncTo(solvedRa, solvedDec)` and emit `sync_applied`. Emits `plate_solve_attempt`, `plate_solve_result`, and `prestep_started/completed/failed` events on `Topic.SEQUENCE`.

- [ ] **Step 11.1: Write the failing test**

Create `src/test/java/dev/nocs/imaging/SlewAndSyncTest.java`:

```java
package dev.nocs.imaging;

import dev.nocs.device.Camera;
import dev.nocs.device.CameraState;
import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceKind;
import dev.nocs.device.Mount;
import dev.nocs.device.MountState;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.image.CaptureContext;
import dev.nocs.image.ImageStoreService;
import dev.nocs.platesolving.FailureKind;
import dev.nocs.platesolving.PlateSolution;
import dev.nocs.platesolving.PlateSolvingService;
import dev.nocs.platesolving.SolveOptions;
import dev.nocs.platesolving.SolveOutcome;
import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@SpringBootTest
class SlewAndSyncTest {

    @Autowired
    ImageStoreService imageStore;
    @Autowired
    EventBus bus;

    private final CopyOnWriteArrayList<Event> seen = new CopyOnWriteArrayList<>();

    @BeforeEach
    void setup() {
        bus.subscribeAll().subscribe(seen::add);
    }

    @Test
    void slewsSolvesAndSyncsWhenFar() throws Exception {
        FakeMount m = new FakeMount();
        FakeCamera c = new FakeCamera(bus, imageStore);
        FakePlateSolver ps = FakePlateSolver.solving(new PlateSolution(
                181.0, 40.1, 1.5, 0, 1, 1, Instant.now(), "fake"));

        SlewAndSync.Context ctx = new SlewAndSync.Context(
                "messier:M31", 180.0, 40.0,
                Duration.ofMillis(100), Duration.ofSeconds(30), 2.0,
                1.0 /* arcmin threshold */, Duration.ofSeconds(5));
        SlewAndSync sut = new SlewAndSync(bus, imageStore, ps);

        SlewAndSync.Result r = sut.execute(m, c, ctx);
        assertThat(r.synced()).isTrue();
        assertThat(m.slewTargets).hasSize(1);
        assertThat(m.syncTargets).hasSize(1);
        assertThat(r.solution()).isNotNull();
        assertThat(seen).anyMatch(e -> e.topic() == Topic.SEQUENCE && "prestep_started".equals(e.type()));
        assertThat(seen).anyMatch(e -> e.topic() == Topic.SEQUENCE && "prestep_completed".equals(e.type()));
        assertThat(seen).anyMatch(e -> e.topic() == Topic.SEQUENCE && "plate_solve_result".equals(e.type()));
        assertThat(seen).anyMatch(e -> e.topic() == Topic.SEQUENCE && "sync_applied".equals(e.type()));
    }

    @Test
    void skipsSyncWhenWithinThreshold() throws Exception {
        FakeMount m = new FakeMount();
        FakeCamera c = new FakeCamera(bus, imageStore);
        FakePlateSolver ps = FakePlateSolver.solving(new PlateSolution(
                180.0, 40.0, 1.5, 0, 1, 1, Instant.now(), "fake"));
        SlewAndSync sut = new SlewAndSync(bus, imageStore, ps);
        SlewAndSync.Result r = sut.execute(m, c, new SlewAndSync.Context(
                "messier:M31", 180.0, 40.0,
                Duration.ofMillis(100), Duration.ofSeconds(30), 2.0,
                5.0, Duration.ofSeconds(5)));
        assertThat(r.synced()).isFalse();
        assertThat(m.syncTargets).isEmpty();
    }

    @Test
    void solveFailureThrows() {
        FakeMount m = new FakeMount();
        FakeCamera c = new FakeCamera(bus, imageStore);
        FakePlateSolver ps = FakePlateSolver.failing("no stars");
        SlewAndSync sut = new SlewAndSync(bus, imageStore, ps);
        assertThatThrownBy(() -> sut.execute(m, c, new SlewAndSync.Context(
                "messier:M31", 180.0, 40.0,
                Duration.ofMillis(100), Duration.ofSeconds(30), 2.0,
                1.0, Duration.ofSeconds(5))))
                .isInstanceOf(RuntimeException.class)
                .hasMessageContaining("solve");
    }

    // --- helpers ---

    private static final class FakeMount implements Mount {
        final CopyOnWriteArrayList<double[]> slewTargets = new CopyOnWriteArrayList<>();
        final CopyOnWriteArrayList<double[]> syncTargets = new CopyOnWriteArrayList<>();
        private MountState s = MountState.IDLE;
        public DeviceId id() { return new DeviceId("m"); }
        public String indiName() { return "m"; }
        public DeviceKind kind() { return DeviceKind.MOUNT; }
        public boolean isConnected() { return s != MountState.DISCONNECTED; }
        public void connect() {}
        public void disconnect() {}
        public MountState state() { return s; }
        public void slew(double r, double d) { slewTargets.add(new double[]{r, d}); s = MountState.TRACKING; }
        public void syncTo(double r, double d) { syncTargets.add(new double[]{r, d}); }
        public void park() {}
        public void unpark() {}
        public void abort() {}
    }

    private static final class FakeCamera implements Camera {
        private final EventBus bus;
        private final ImageStoreService store;
        FakeCamera(EventBus bus, ImageStoreService store) { this.bus = bus; this.store = store; }
        public DeviceId id() { return new DeviceId("cam"); }
        public String indiName() { return "cam"; }
        public DeviceKind kind() { return DeviceKind.CAMERA; }
        public boolean isConnected() { return true; }
        public void connect() {}
        public void disconnect() {}
        public CameraState state() { return CameraState.IDLE; }
        public void cool(double x) {}
        public void expose(double x) {
            // Synthesize a tiny FITS blob using MiniFits and pipe through ImageStore as if the
            // INDI BLOB arrived.
            Thread.ofVirtual().start(() -> {
                try { Thread.sleep(30); } catch (InterruptedException ignored) {}
                byte[] bytes = dev.nocs.image.MiniFits.oneByOneZero();
                store.accept(id(), bytes, ".fits");
            });
        }
        public void abortExposure() {}
        public Double currentTemperatureCelsius() { return null; }
    }

    private static final class FakePlateSolver implements PlateSolvingService {
        private final SolveOutcome outcome;
        FakePlateSolver(SolveOutcome o) { this.outcome = o; }
        public static FakePlateSolver solving(PlateSolution s) {
            return new FakePlateSolver(new SolveOutcome.Solved(s, 10L));
        }
        public static FakePlateSolver failing(String msg) {
            return new FakePlateSolver(new SolveOutcome.Failed(FailureKind.UNKNOWN, msg, 10L));
        }
        public SolveOutcome solve(byte[] fits, SolveOptions options) { return outcome; }
        public boolean isAvailable() { return true; }
    }
}
```

> **Note:** `dev.nocs.image.MiniFits` is a test helper already present in `src/test/java/dev/nocs/image/MiniFits.java` (from Plan D).

- [ ] **Step 11.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.imaging.SlewAndSyncTest'`
Expected: compile failure — `SlewAndSync` missing.

- [ ] **Step 11.3: Implement `SlewAndSync`**

Create `src/main/java/dev/nocs/imaging/SlewAndSync.java`:

```java
package dev.nocs.imaging;

import dev.nocs.device.Camera;
import dev.nocs.device.Mount;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.image.CaptureContext;
import dev.nocs.image.ImageStoreService;
import dev.nocs.platesolving.PlateSolution;
import dev.nocs.platesolving.PlateSolvingService;
import dev.nocs.platesolving.SolveOptions;
import dev.nocs.platesolving.SolveOutcome;
import java.time.Duration;
import java.time.Instant;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class SlewAndSync {

    private static final Logger log = LoggerFactory.getLogger(SlewAndSync.class);

    private final EventBus bus;
    private final ImageStoreService imageStore;
    private final PlateSolvingService solver;

    public SlewAndSync(EventBus bus, ImageStoreService imageStore, PlateSolvingService solver) {
        this.bus = bus;
        this.imageStore = imageStore;
        this.solver = solver;
    }

    public Result execute(Mount mount, Camera camera, Context ctx) {
        bus.publish(Event.of(Topic.SEQUENCE, "prestep_started", Map.of(
                "type", "slew_and_sync",
                "target", ctx.targetId(),
                "ra_hours", ctx.targetRaHours(),
                "dec_deg", ctx.targetDecDeg())));

        // 1. Slew.
        bus.publish(Event.of(Topic.SEQUENCE, "slew_started", Map.of(
                "target", ctx.targetId(),
                "ra_hours", ctx.targetRaHours(),
                "dec_deg", ctx.targetDecDeg())));
        mount.slew(ctx.targetRaHours(), ctx.targetDecDeg());
        sleep(ctx.settle().toMillis());
        bus.publish(Event.of(Topic.SEQUENCE, "slew_completed", Map.of(
                "target", ctx.targetId(),
                "state", mount.state().name().toLowerCase())));

        // 2. Test expose.
        CaptureContext cap = new CaptureContext(
                "TEST", ctx.targetId(), ctx.testExposureSec(), "__prestep", 1);
        imageStore.prepareCapture(camera.id(), cap);
        ImageAwait awaitHelper = new ImageAwait(bus);
        CompletableFuture<Long> imageIdF = awaitHelper.waitFor(
                camera.id(), cap.target(), cap.step(), cap.seq(),
                Duration.ofMillis(Math.max(5_000L, (long) (ctx.testExposureSec() * 1000L * 4L))));
        camera.expose(ctx.testExposureSec());
        long imageId;
        try {
            imageId = imageIdF.get(ctx.imageAwaitTimeout().toMillis(), TimeUnit.MILLISECONDS);
        } catch (Exception e) {
            bus.publish(Event.of(Topic.SEQUENCE, "prestep_failed", Map.of(
                    "type", "slew_and_sync",
                    "reason", "image_await_timeout")));
            throw new RuntimeException("slew_and_sync: image await failed", e);
        }

        // 3. Solve.
        bus.publish(Event.of(Topic.SEQUENCE, "plate_solve_attempt", Map.of(
                "target", ctx.targetId(),
                "image_id", imageId,
                "timeout_sec", ctx.solveTimeout().toSeconds())));
        Optional<byte[]> bytes = imageStore.loadFits(imageId);
        if (bytes.isEmpty()) {
            bus.publish(Event.of(Topic.SEQUENCE, "prestep_failed", Map.of(
                    "type", "slew_and_sync", "reason", "fits_missing", "image_id", imageId)));
            throw new RuntimeException("slew_and_sync: fits bytes missing for " + imageId);
        }
        SolveOptions opts = new SolveOptions(
                ctx.targetRaHours() * 15.0, ctx.targetDecDeg(), 5.0, null,
                (double) ctx.solveTimeout().toSeconds());
        SolveOutcome outcome = solver.solve(bytes.get(), opts);
        if (outcome instanceof SolveOutcome.Failed f) {
            bus.publish(Event.of(Topic.SEQUENCE, "plate_solve_result", Map.of(
                    "target", ctx.targetId(),
                    "image_id", imageId,
                    "status", "failed",
                    "failure_kind", f.kind().wire(),
                    "message", f.message())));
            bus.publish(Event.of(Topic.SEQUENCE, "prestep_failed", Map.of(
                    "type", "slew_and_sync",
                    "reason", "solve_failed",
                    "failure_kind", f.kind().wire())));
            throw new RuntimeException("slew_and_sync: solve failed: " + f.message());
        }
        PlateSolution sol = ((SolveOutcome.Solved) outcome).solution();
        Map<String, Object> solvedPayload = new LinkedHashMap<>();
        solvedPayload.put("target", ctx.targetId());
        solvedPayload.put("image_id", imageId);
        solvedPayload.put("status", "solved");
        solvedPayload.put("ra_j2000_deg", sol.raJ2000Deg());
        solvedPayload.put("dec_j2000_deg", sol.decJ2000Deg());
        solvedPayload.put("pixel_scale_arcsec_per_px", sol.pixelScaleArcsecPerPx());
        bus.publish(Event.of(Topic.SEQUENCE, "plate_solve_result", solvedPayload));

        // 4. Sync if far enough.
        double solvedRaHours = sol.raJ2000Deg() / 15.0;
        double offsetArcmin = offsetArcmin(ctx.targetRaHours(), ctx.targetDecDeg(), solvedRaHours, sol.decJ2000Deg());
        boolean synced = false;
        if (offsetArcmin > ctx.syncThresholdArcmin()) {
            mount.syncTo(solvedRaHours, sol.decJ2000Deg());
            synced = true;
            Map<String, Object> syncPayload = new HashMap<>();
            syncPayload.put("target", ctx.targetId());
            syncPayload.put("offset_arcmin", offsetArcmin);
            syncPayload.put("synced_ra_hours", solvedRaHours);
            syncPayload.put("synced_dec_deg", sol.decJ2000Deg());
            bus.publish(Event.of(Topic.SEQUENCE, "sync_applied", syncPayload));
        }

        bus.publish(Event.of(Topic.SEQUENCE, "prestep_completed", Map.of(
                "type", "slew_and_sync",
                "synced", synced,
                "offset_arcmin", offsetArcmin)));

        return new Result(sol, imageId, synced, offsetArcmin, Instant.now());
    }

    private static double offsetArcmin(double targetRaHours, double targetDec, double solvedRaHours, double solvedDec) {
        double cosDec = Math.cos(Math.toRadians((targetDec + solvedDec) / 2.0));
        double deltaRaArcmin = (solvedRaHours - targetRaHours) * 15.0 * 60.0 * Math.max(0.05, cosDec);
        double deltaDecArcmin = (solvedDec - targetDec) * 60.0;
        return Math.sqrt(deltaRaArcmin * deltaRaArcmin + deltaDecArcmin * deltaDecArcmin);
    }

    private static void sleep(long ms) {
        if (ms <= 0) return;
        try {
            Thread.sleep(ms);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    public record Context(
            String targetId,
            double targetRaHours,
            double targetDecDeg,
            Duration settle,
            Duration solveTimeout,
            double testExposureSec,
            double syncThresholdArcmin,
            Duration imageAwaitTimeout) {}

    public record Result(
            PlateSolution solution,
            long imageId,
            boolean synced,
            double offsetArcmin,
            Instant finishedAt) {}
}
```

- [ ] **Step 11.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.imaging.SlewAndSyncTest'`
Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 11.5: Commit**

```bash
git add src/main/java/dev/nocs/imaging/SlewAndSync.java \
        src/test/java/dev/nocs/imaging/SlewAndSyncTest.java
git commit -m "feat(imaging): SlewAndSync pre-step helper (slew → solve → sync)"
```

---

### Task 12: `SequenceEngine` (core loop)

**Files:**
- Create: `src/main/java/dev/nocs/imaging/SequenceEngine.java`
- Create: `src/test/java/dev/nocs/imaging/SequenceEngineTest.java`

The engine executes a `SequenceRun`: pre-steps → for each step, switch filter, loop subs (prepare capture context, trigger expose, await saved, optionally dither, respect pause/abort), emit events throughout.

- [ ] **Step 12.1: Write the failing test**

Create `src/test/java/dev/nocs/imaging/SequenceEngineTest.java`:

```java
package dev.nocs.imaging;

import dev.nocs.device.Camera;
import dev.nocs.device.CameraState;
import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceKind;
import dev.nocs.device.FilterWheel;
import dev.nocs.device.FilterWheelState;
import dev.nocs.device.Focuser;
import dev.nocs.device.FocuserState;
import dev.nocs.device.Mount;
import dev.nocs.device.MountState;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.image.ImageStoreService;
import dev.nocs.platesolving.PlateSolution;
import dev.nocs.platesolving.PlateSolvingService;
import dev.nocs.platesolving.SolveOptions;
import dev.nocs.platesolving.SolveOutcome;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
class SequenceEngineTest {

    @Autowired
    ImageStoreService imageStore;
    @Autowired
    EventBus bus;

    @Test
    void happyPathRunsAllSubsAndCompletes() throws Exception {
        SequenceDefinition def = new SequenceDefinition(
                "m31-mini", "messier:M31",
                new DitherOptions(true, 5, 1),
                List.of(),
                List.of(new SequenceStep("L", 0.2, 2, null), new SequenceStep("R", 0.2, 1, null)),
                null);
        FakeMount m = new FakeMount();
        FakeCamera c = new FakeCamera(imageStore);
        FakeWheel w = new FakeWheel();
        FakeFocuser f = new FakeFocuser();
        m.connect(); c.connect(); w.connect(); f.connect();
        FakePlateSolver ps = new FakePlateSolver(
                new PlateSolution(180.0, 40.0, 1.5, 0, 1, 1, Instant.now(), "fake"));

        CopyOnWriteArrayList<Event> seen = new CopyOnWriteArrayList<>();
        bus.subscribeAll().subscribe(seen::add);

        SequenceEngine engine = new SequenceEngine(
                bus, imageStore, new ImageAwait(bus), new PixelOffsetDitherStrategy(42L),
                new NoopAutofocusStrategy(), ps, engineConfig());
        SequenceEngine.Outcome outcome = engine.run(
                1L, def, 180.0, 40.0,
                new DeviceSelector.Resolved(m, c, w, f), new PauseAbortLatch());

        assertThat(outcome.status()).isEqualTo(SequenceStatus.COMPLETED);
        assertThat(c.exposures).isEqualTo(3);
        assertThat(seen).anyMatch(e -> e.topic() == Topic.SEQUENCE && "sequence_completed".equals(e.type()));
        assertThat(seen).anyMatch(e -> e.topic() == Topic.SEQUENCE && "step_completed".equals(e.type()));
    }

    @Test
    void abortDuringSubStopsImmediately() throws Exception {
        SequenceDefinition def = new SequenceDefinition(
                "m31-abort", "messier:M31",
                DitherOptions.disabled(),
                List.of(),
                List.of(new SequenceStep("L", 0.5, 3, null)),
                null);
        FakeMount m = new FakeMount();
        FakeCamera c = new FakeCamera(imageStore);
        FakeWheel w = new FakeWheel();
        FakeFocuser f = new FakeFocuser();
        m.connect(); c.connect(); w.connect(); f.connect();
        FakePlateSolver ps = new FakePlateSolver(
                new PlateSolution(180.0, 40.0, 1.5, 0, 1, 1, Instant.now(), "fake"));

        PauseAbortLatch latch = new PauseAbortLatch();
        Thread.ofVirtual().start(() -> {
            try { Thread.sleep(200); } catch (InterruptedException ignored) {}
            latch.abort("test");
        });
        SequenceEngine engine = new SequenceEngine(
                bus, imageStore, new ImageAwait(bus), new PixelOffsetDitherStrategy(42L),
                new NoopAutofocusStrategy(), ps, engineConfig());
        SequenceEngine.Outcome outcome = engine.run(
                2L, def, 180.0, 40.0,
                new DeviceSelector.Resolved(m, c, w, f), latch);

        assertThat(outcome.status()).isEqualTo(SequenceStatus.ABORTED);
        assertThat(c.exposures).isLessThanOrEqualTo(3);
    }

    private static SequenceEngine.EngineConfig engineConfig() {
        return new SequenceEngine.EngineConfig(
                Duration.ofMillis(50),  // slewSettle
                1.0,                    // syncThresholdArcmin
                Duration.ofSeconds(5),  // postSlewSolveTimeout
                0.2,                    // testExposureSec
                Duration.ofMillis(0),   // ditherSettle
                Duration.ofSeconds(5)); // imageAwaitTimeout
    }

    // --- fakes ---

    private static final class FakeMount implements Mount {
        private MountState s = MountState.DISCONNECTED;
        double curRa = 12.0, curDec = 40.0;
        public DeviceId id() { return new DeviceId("m"); }
        public String indiName() { return "m"; }
        public DeviceKind kind() { return DeviceKind.MOUNT; }
        public boolean isConnected() { return s != MountState.DISCONNECTED; }
        public void connect() { s = MountState.IDLE; }
        public void disconnect() { s = MountState.DISCONNECTED; }
        public MountState state() { return s; }
        public void slew(double r, double d) { curRa = r; curDec = d; s = MountState.TRACKING; }
        public void syncTo(double r, double d) { curRa = r; curDec = d; }
        public void park() { s = MountState.PARKED; }
        public void unpark() { s = MountState.IDLE; }
        public void abort() {}
    }

    private static final class FakeCamera implements Camera {
        private final ImageStoreService store;
        int exposures;
        FakeCamera(ImageStoreService s) { this.store = s; }
        public DeviceId id() { return new DeviceId("cam"); }
        public String indiName() { return "cam"; }
        public DeviceKind kind() { return DeviceKind.CAMERA; }
        public boolean isConnected() { return true; }
        public void connect() {}
        public void disconnect() {}
        public CameraState state() { return CameraState.IDLE; }
        public void cool(double x) {}
        public void expose(double s) {
            exposures++;
            Thread.ofVirtual().start(() -> {
                try { Thread.sleep(30); } catch (InterruptedException ignored) {}
                store.accept(id(), dev.nocs.image.MiniFits.oneByOneZero(), ".fits");
            });
        }
        public void abortExposure() {}
        public Double currentTemperatureCelsius() { return null; }
    }

    private static final class FakeWheel implements FilterWheel {
        int slot = 1;
        private FilterWheelState s = FilterWheelState.DISCONNECTED;
        public DeviceId id() { return new DeviceId("w"); }
        public String indiName() { return "w"; }
        public DeviceKind kind() { return DeviceKind.FILTERWHEEL; }
        public boolean isConnected() { return s != FilterWheelState.DISCONNECTED; }
        public void connect() { s = FilterWheelState.IDLE; }
        public void disconnect() { s = FilterWheelState.DISCONNECTED; }
        public FilterWheelState state() { return s; }
        public List<String> slotNames() { return List.of("L", "R", "G", "B"); }
        public int currentSlot() { return slot; }
        public void selectSlot(int slotNumber) { slot = slotNumber; }
    }

    private static final class FakeFocuser implements Focuser {
        public DeviceId id() { return new DeviceId("f"); }
        public String indiName() { return "f"; }
        public DeviceKind kind() { return DeviceKind.FOCUSER; }
        public boolean isConnected() { return true; }
        public void connect() {}
        public void disconnect() {}
        public FocuserState state() { return FocuserState.IDLE; }
        public int currentPosition() { return 25_000; }
        public void moveAbsolute(int p) {}
        public void moveRelative(int d) {}
        public void abort() {}
    }

    private static final class FakePlateSolver implements PlateSolvingService {
        private final PlateSolution sol;
        FakePlateSolver(PlateSolution s) { this.sol = s; }
        public SolveOutcome solve(byte[] fits, SolveOptions opts) { return new SolveOutcome.Solved(sol, 5L); }
        public boolean isAvailable() { return true; }
    }
}
```

- [ ] **Step 12.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.imaging.SequenceEngineTest'`
Expected: compile failure.

- [ ] **Step 12.3: Implement `SequenceEngine`**

Create `src/main/java/dev/nocs/imaging/SequenceEngine.java`:

```java
package dev.nocs.imaging;

import dev.nocs.device.Camera;
import dev.nocs.device.FilterWheel;
import dev.nocs.device.FilterWheelState;
import dev.nocs.device.Focuser;
import dev.nocs.device.Mount;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.image.CaptureContext;
import dev.nocs.image.ImageStoreService;
import dev.nocs.platesolving.PlateSolution;
import dev.nocs.platesolving.PlateSolvingService;
import java.time.Duration;
import java.time.Instant;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class SequenceEngine {

    private static final Logger log = LoggerFactory.getLogger(SequenceEngine.class);

    private final EventBus bus;
    private final ImageStoreService imageStore;
    private final ImageAwait imageAwait;
    private final DitherStrategy ditherStrategy;
    private final AutofocusStrategy autofocusStrategy;
    private final PlateSolvingService solver;
    private final EngineConfig cfg;

    public SequenceEngine(
            EventBus bus,
            ImageStoreService imageStore,
            ImageAwait imageAwait,
            DitherStrategy ditherStrategy,
            AutofocusStrategy autofocusStrategy,
            PlateSolvingService solver,
            EngineConfig cfg) {
        this.bus = bus;
        this.imageStore = imageStore;
        this.imageAwait = imageAwait;
        this.ditherStrategy = ditherStrategy;
        this.autofocusStrategy = autofocusStrategy;
        this.solver = solver;
        this.cfg = cfg;
    }

    public Outcome run(
            long runId,
            SequenceDefinition def,
            double targetRaHours,
            double targetDecDeg,
            DeviceSelector.Resolved devices,
            PauseAbortLatch latch) {
        emit("sequence_started", Map.of("run_id", runId, "target", def.targetId(), "subs_total", def.totalSubs()));
        emit("target_active", Map.of(
                "target_id", def.targetId(),
                "ra_j2000_deg", targetRaHours * 15.0,
                "dec_j2000_deg", targetDecDeg));

        AtomicReference<PlateSolution> lastSolution = new AtomicReference<>();
        AtomicReference<double[]> currentRaDec = new AtomicReference<>(new double[] {targetRaHours, targetDecDeg});

        try {
            // Pre-steps.
            for (PreStep ps : def.preSteps()) {
                if (latch.isAbortRequested()) return abort(runId, latch.abortReason());
                if (ps instanceof PreStep.SlewAndSyncStep) {
                    SlewAndSync helper = new SlewAndSync(bus, imageStore, solver);
                    SlewAndSync.Context ctx = new SlewAndSync.Context(
                            def.targetId(),
                            targetRaHours,
                            targetDecDeg,
                            cfg.slewSettle(),
                            cfg.postSlewSolveTimeout(),
                            cfg.testExposureSec(),
                            cfg.syncThresholdArcmin(),
                            cfg.imageAwaitTimeout());
                    SlewAndSync.Result r = helper.execute(devices.mount(), devices.camera(), ctx);
                    lastSolution.set(r.solution());
                    currentRaDec.set(new double[] {
                            r.solution().raJ2000Deg() / 15.0, r.solution().decJ2000Deg()});
                } else if (ps instanceof PreStep.AutofocusStep) {
                    emit("prestep_started", Map.of("type", "autofocus", "target", def.targetId()));
                    emit("autofocus_started", Map.of("target", def.targetId()));
                    AutofocusStrategy.AutofocusResult res = autofocusStrategy.run(
                            devices.focuser(), devices.camera(),
                            new AutofocusStrategy.AutofocusContext(def.targetId(), Instant.now()));
                    emit("autofocus_completed", Map.of(
                            "target", def.targetId(),
                            "best_position", res.bestPosition(),
                            "points_tried", res.pointsTried(),
                            "duration_ms", res.durationMs()));
                    emit("prestep_completed", Map.of("type", "autofocus"));
                }
            }

            // Steps.
            int subsCompleted = 0;
            for (int stepIdx = 0; stepIdx < def.steps().size(); stepIdx++) {
                if (latch.isAbortRequested()) return abort(runId, latch.abortReason());
                SequenceStep step = def.steps().get(stepIdx);
                selectFilter(devices.filterWheel(), step.filter());
                emit("step_started", Map.of(
                        "run_id", runId,
                        "step_index", stepIdx,
                        "filter", step.filter(),
                        "count", step.count(),
                        "exposure_s", step.exposureSec()));

                for (int sub = 1; sub <= step.count(); sub++) {
                    if (latch.isAbortRequested()) return abort(runId, latch.abortReason());
                    latch.awaitIfPaused(Duration.ofMinutes(60));
                    if (latch.isAbortRequested()) return abort(runId, latch.abortReason());

                    CaptureContext cap = new CaptureContext(
                            step.filter(), def.targetId(), step.exposureSec(), step.name(), sub);
                    emit("sub_started", Map.of(
                            "run_id", runId,
                            "step_index", stepIdx,
                            "filter", step.filter(),
                            "seq", sub,
                            "exposure_s", step.exposureSec()));

                    imageStore.prepareCapture(devices.camera().id(), cap);
                    Duration imageTimeout = Duration.ofMillis(
                            Math.max(cfg.imageAwaitTimeout().toMillis(),
                                    (long) (step.exposureSec() * 1000.0 * 4.0) + 10_000L));
                    CompletableFuture<Long> imageF = imageAwait.waitFor(
                            devices.camera().id(), def.targetId(), step.name(), sub, imageTimeout);
                    try {
                        devices.camera().expose(step.exposureSec());
                    } catch (RuntimeException e) {
                        // Camera may already be E_STOPPED (safety dispatcher beat us). Mark abort.
                        return abort(runId, "camera_rejected:" + e.getMessage());
                    }
                    long imageId;
                    try {
                        imageId = imageF.get(imageTimeout.toMillis(), TimeUnit.MILLISECONDS);
                    } catch (Exception e) {
                        if (latch.isAbortRequested()) return abort(runId, latch.abortReason());
                        emit("sub_failed", Map.of(
                                "run_id", runId,
                                "step_index", stepIdx,
                                "seq", sub,
                                "reason", "image_await_timeout"));
                        return failed(runId, "image_await_timeout");
                    }

                    emit("sub_completed", Map.of(
                            "run_id", runId,
                            "step_index", stepIdx,
                            "seq", sub,
                            "image_id", imageId));
                    subsCompleted++;

                    if (def.dither().shouldDither(sub) && sub < step.count()) {
                        double[] cur = currentRaDec.get();
                        emit("dither_started", Map.of(
                                "run_id", runId,
                                "step_index", stepIdx,
                                "seq", sub,
                                "pixels", def.dither().pixels()));
                        DitherStrategy.DitherResult dr = ditherStrategy.dither(
                                devices.mount(), lastSolution.get(),
                                cur[0], cur[1], def.dither().pixels(), cfg.ditherSettle().toMillis());
                        if (dr.skipped()) {
                            emit("dither_completed", Map.of(
                                    "run_id", runId,
                                    "skipped", true,
                                    "reason", dr.skipReason() == null ? "" : dr.skipReason()));
                        } else {
                            currentRaDec.set(new double[] {dr.newRaHours(), dr.newDecDeg()});
                            emit("dither_completed", Map.of(
                                    "run_id", runId,
                                    "skipped", false,
                                    "new_ra_hours", dr.newRaHours(),
                                    "new_dec_deg", dr.newDecDeg()));
                        }
                    }
                }

                emit("step_completed", Map.of(
                        "run_id", runId,
                        "step_index", stepIdx,
                        "subs_done", step.count()));
            }

            emit("sequence_completed", Map.of("run_id", runId, "subs_completed", subsCompleted));
            return new Outcome(SequenceStatus.COMPLETED, null);
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
            return abort(runId, "interrupted");
        } catch (SequenceSetupException se) {
            emit("sequence_failed", Map.of("run_id", runId, "reason", se.getMessage()));
            return new Outcome(SequenceStatus.FAILED, se.getMessage());
        } catch (RuntimeException re) {
            if (latch.isAbortRequested()) {
                return abort(runId, latch.abortReason());
            }
            log.error("sequence {} failed: {}", runId, re.getMessage(), re);
            emit("sequence_failed", Map.of("run_id", runId, "reason", re.getMessage() == null ? "unknown" : re.getMessage()));
            return new Outcome(SequenceStatus.FAILED, re.getMessage());
        }
    }

    private Outcome abort(long runId, String reason) {
        emit("sequence_aborted", Map.of("run_id", runId, "reason", reason == null ? "" : reason));
        return new Outcome(SequenceStatus.ABORTED, reason);
    }

    private Outcome failed(long runId, String reason) {
        emit("sequence_failed", Map.of("run_id", runId, "reason", reason));
        return new Outcome(SequenceStatus.FAILED, reason);
    }

    private void selectFilter(FilterWheel wheel, String filterName) {
        List<String> names = wheel.slotNames();
        int slot = -1;
        for (int i = 0; i < names.size(); i++) {
            if (names.get(i).equalsIgnoreCase(filterName)) {
                slot = i + 1;
                break;
            }
        }
        if (slot <= 0) {
            throw new SequenceSetupException(
                    SequenceSetupException.Kind.INVALID_DEFINITION,
                    "filter " + filterName + " not found in wheel slots " + names);
        }
        if (wheel.currentSlot() == slot && wheel.state() == FilterWheelState.IDLE) {
            return;
        }
        wheel.selectSlot(slot);
        long deadline = System.nanoTime() + Duration.ofSeconds(30).toNanos();
        while (wheel.state() != FilterWheelState.IDLE && System.nanoTime() < deadline) {
            try { Thread.sleep(50); } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                return;
            }
        }
    }

    private void emit(String type, Map<String, Object> payload) {
        bus.publish(Event.of(Topic.SEQUENCE, type, payload instanceof LinkedHashMap<?, ?> ? payload : new LinkedHashMap<>(payload)));
    }

    public record Outcome(SequenceStatus status, String failureReason) {}

    public record EngineConfig(
            Duration slewSettle,
            double syncThresholdArcmin,
            Duration postSlewSolveTimeout,
            double testExposureSec,
            Duration ditherSettle,
            Duration imageAwaitTimeout) {}
}
```

- [ ] **Step 12.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.imaging.SequenceEngineTest'`
Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 12.5: Commit**

```bash
git add src/main/java/dev/nocs/imaging/SequenceEngine.java \
        src/test/java/dev/nocs/imaging/SequenceEngineTest.java
git commit -m "feat(imaging): SequenceEngine core loop (pre-steps, subs, dither, pause/abort)"
```

---

### Task 13: `ImagingService` (facade)

**Files:**
- Create: `src/main/java/dev/nocs/imaging/ImagingService.java`
- Create: `src/test/java/dev/nocs/imaging/ImagingServiceTest.java`

`ImagingService` is the single public entry point: accepts a `SequenceDefinition`, resolves target + devices, persists a `SequenceRun`, spawns a virtual thread to execute via `SequenceEngine`, subscribes to bus `SEQUENCE/pause_requested` + `abort_requested`, and serves `pause(id)`, `resume(id)`, `abort(id, reason)`.

- [ ] **Step 13.1: Write the failing test**

Create `src/test/java/dev/nocs/imaging/ImagingServiceTest.java`:

```java
package dev.nocs.imaging;

import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@SpringBootTest
class ImagingServiceTest {

    @Autowired
    ImagingService imaging;
    @Autowired
    EventBus bus;

    @Test
    void submitWithoutDevicesThrowsSetupException() {
        // With no devices connected the submission should fail fast with SequenceSetupException
        // before any run is registered as active. Full end-to-end behaviour is covered by the
        // Integration* tests.
        SequenceDefinition d = new SequenceDefinition(
                "conflict", "messier:M31",
                DitherOptions.disabled(),
                List.of(),
                List.of(new SequenceStep("L", 60, 1, null)),
                null);
        assertThatThrownBy(() -> imaging.submit(d))
                .isInstanceOf(SequenceSetupException.class);
    }

    @Test
    void busEventsAreSwallowedWhenNoActiveRun() {
        // ImagingService subscribes to Topic.SEQUENCE. A pause_requested or abort_requested bus
        // event with no active run must not throw.
        bus.publish(Event.of(Topic.SEQUENCE, "pause_requested", Map.of("reason", "rule:noop")));
        bus.publish(Event.of(Topic.SEQUENCE, "abort_requested", Map.of("reason", "rule:noop")));
        assertThat(imaging.progress(-1L)).isEmpty();
    }
}
```

- [ ] **Step 13.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.imaging.ImagingServiceTest'`
Expected: compile failure.

- [ ] **Step 13.3: Implement `ImagingService`**

Create `src/main/java/dev/nocs/imaging/ImagingService.java`:

```java
package dev.nocs.imaging;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.imaging.api.dto.SequenceDefinitionDto;
import dev.nocs.session.Session;
import dev.nocs.session.SessionService;
import dev.nocs.target.Target;
import dev.nocs.target.TargetService;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import java.time.Instant;
import java.util.EnumSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicReference;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Service;
import reactor.core.Disposable;

@Service
public class ImagingService {

    private static final Logger log = LoggerFactory.getLogger(ImagingService.class);

    private final EventBus bus;
    private final SequenceRepository repo;
    private final DeviceSelector deviceSelector;
    private final TargetService targetService;
    private final SequenceEngine engine;
    private final ObjectMapper mapper;
    private final ObjectProvider<SessionService> sessions;
    private final ExecutorService runner;
    private final AtomicReference<ActiveRun> active = new AtomicReference<>();
    private Disposable subscription;

    public ImagingService(
            EventBus bus,
            SequenceRepository repo,
            DeviceSelector deviceSelector,
            TargetService targetService,
            SequenceEngine engine,
            ObjectMapper mapper,
            ObjectProvider<SessionService> sessions) {
        this.bus = bus;
        this.repo = repo;
        this.deviceSelector = deviceSelector;
        this.targetService = targetService;
        this.engine = engine;
        this.mapper = mapper;
        this.sessions = sessions;
        this.runner = Executors.newThreadPerTaskExecutor(
                Thread.ofVirtual().name("sequence-runner-", 0).factory());
    }

    @PostConstruct
    public void start() {
        subscription = bus.subscribe(EnumSet.of(Topic.SEQUENCE)).subscribe(this::onBusEvent);
    }

    @PreDestroy
    public void stop() {
        if (subscription != null) subscription.dispose();
        ActiveRun a = active.get();
        if (a != null) a.latch.abort("shutdown");
        runner.shutdownNow();
    }

    public synchronized long submit(SequenceDefinition def) {
        if (active.get() != null) {
            throw new IllegalStateException("another sequence is active; only one run allowed in v0.1");
        }
        var resolvedTarget = targetService.resolveById(def.targetId(), Instant.now())
                .orElseThrow(() -> new SequenceSetupException(
                        SequenceSetupException.Kind.TARGET_NOT_FOUND, "target not found: " + def.targetId()));
        Target t = resolvedTarget.target();
        if (!t.hasFixedCoordinates()) {
            throw new SequenceSetupException(
                    SequenceSetupException.Kind.TARGET_UNRESOLVABLE,
                    "target has no fixed coordinates: " + def.targetId());
        }
        DeviceSelector.Resolved devices = deviceSelector.resolve(def.deviceIds());
        String json;
        try {
            json = mapper.writeValueAsString(SequenceDefinitionDto.fromDomain(def));
        } catch (Exception e) {
            throw new SequenceSetupException(
                    SequenceSetupException.Kind.INVALID_DEFINITION, "definition not serialisable");
        }
        Long sessionId = currentSessionId();
        long id = repo.insert(SequenceRun.forInsert(sessionId, def.name(), json, def.totalSubs()));
        bus.publish(Event.of(Topic.SEQUENCE, "sequence_submitted", Map.of(
                "run_id", id, "name", def.name(), "target", def.targetId())));

        PauseAbortLatch latch = new PauseAbortLatch();
        ActiveRun run = new ActiveRun(id, def, devices, latch);
        if (!active.compareAndSet(null, run)) {
            throw new IllegalStateException("race: another run was submitted");
        }
        double raHours = t.raJ2000Deg() / 15.0;
        double decDeg = t.decJ2000Deg();
        runner.submit(() -> execute(run, raHours, decDeg));
        return id;
    }

    public void pause(long id) {
        ActiveRun a = requireActive(id);
        a.latch.pause();
        repo.updateStatus(id, SequenceStatus.PAUSED, null, null, null);
        bus.publish(Event.of(Topic.SEQUENCE, "sequence_paused", Map.of("run_id", id)));
    }

    public void resume(long id) {
        ActiveRun a = requireActive(id);
        a.latch.resume();
        repo.updateStatus(id, SequenceStatus.RUNNING, null, null, null);
        bus.publish(Event.of(Topic.SEQUENCE, "sequence_resumed", Map.of("run_id", id)));
    }

    public void abort(long id, String reason) {
        ActiveRun a = active.get();
        if (a == null || a.runId != id) {
            throw new IllegalStateException("no active run with id " + id);
        }
        a.latch.abort(reason == null ? "user" : reason);
        // Best-effort abort of in-flight exposure (engine also checks the latch at the next sub).
        try {
            a.devices.camera().abortExposure();
        } catch (RuntimeException e) {
            log.debug("abortExposure swallowed: {}", e.getMessage());
        }
    }

    public Optional<SequenceRun> find(long id) {
        return repo.findById(id);
    }

    public List<SequenceRun> list(SequenceRepository.Filters f) {
        return repo.list(f);
    }

    public Optional<SequenceProgress> progress(long id) {
        ActiveRun a = active.get();
        if (a != null && a.runId == id) {
            return repo.findById(id).map(r -> new SequenceProgress(
                    id, r.status(),
                    r.currentStepIndex() == null ? 0 : r.currentStepIndex(),
                    r.currentSubIndex() == null ? 0 : r.currentSubIndex(),
                    r.subsCompleted(), r.subsTotal(), ""));
        }
        return repo.findById(id).map(r -> new SequenceProgress(
                id, r.status(), 0, 0, r.subsCompleted(), r.subsTotal(),
                r.failureReason() == null ? "" : r.failureReason()));
    }

    private void execute(ActiveRun run, double raHours, double decDeg) {
        Instant started = Instant.now();
        repo.updateStatus(run.runId, SequenceStatus.RUNNING, null, started, null);
        logSession("sequence", "started", Map.of("run_id", run.runId, "target", run.def.targetId()));
        try {
            SequenceEngine.Outcome outcome = engine.run(
                    run.runId, run.def, raHours, decDeg, run.devices, run.latch);
            Instant finished = Instant.now();
            repo.updateStatus(run.runId, outcome.status(), outcome.failureReason(), null, finished);
            logSession("sequence", outcome.status().wire().toLowerCase(), Map.of(
                    "run_id", run.runId,
                    "status", outcome.status().wire(),
                    "reason", outcome.failureReason() == null ? "" : outcome.failureReason()));
        } catch (RuntimeException e) {
            log.error("sequence runner failed unexpectedly for run {}: {}", run.runId, e.getMessage(), e);
            repo.updateStatus(run.runId, SequenceStatus.FAILED, e.getMessage(), null, Instant.now());
            bus.publish(Event.of(Topic.SEQUENCE, "sequence_failed", Map.of(
                    "run_id", run.runId, "reason", e.getMessage() == null ? "unknown" : e.getMessage())));
        } finally {
            active.compareAndSet(run, null);
        }
    }

    private void onBusEvent(Event event) {
        ActiveRun a = active.get();
        if (a == null) return;
        if (event.topic() != Topic.SEQUENCE) return;
        switch (event.type()) {
            case "pause_requested" -> {
                if (a.latch.isPaused()) return;
                a.latch.pause();
                repo.updateStatus(a.runId, SequenceStatus.PAUSED, null, null, null);
                bus.publish(Event.of(Topic.SEQUENCE, "sequence_paused", Map.of(
                        "run_id", a.runId,
                        "reason", stringOrEmpty(event.payload().get("reason")))));
            }
            case "abort_requested" -> {
                String reason = stringOrEmpty(event.payload().get("reason"));
                a.latch.abort(reason.isBlank() ? "requested" : reason);
                try {
                    a.devices.camera().abortExposure();
                } catch (RuntimeException e) {
                    log.debug("abortExposure swallowed during bus abort: {}", e.getMessage());
                }
            }
            default -> {
                // other SEQUENCE events are informational only
            }
        }
    }

    private static String stringOrEmpty(Object o) {
        return o == null ? "" : o.toString();
    }

    private ActiveRun requireActive(long id) {
        ActiveRun a = active.get();
        if (a == null || a.runId != id) {
            throw new IllegalStateException("no active run with id " + id);
        }
        return a;
    }

    private Long currentSessionId() {
        SessionService svc = sessions.getIfAvailable();
        if (svc == null) return null;
        Session s = svc.current();
        return s == null ? null : s.id();
    }

    private void logSession(String topic, String type, Map<String, Object> payload) {
        SessionService svc = sessions.getIfAvailable();
        if (svc != null) svc.logEvent(topic, type, payload);
    }

    private record ActiveRun(
            long runId,
            SequenceDefinition def,
            DeviceSelector.Resolved devices,
            PauseAbortLatch latch) {}
}
```

- [ ] **Step 13.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.imaging.ImagingServiceTest'`
Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 13.5: Commit**

```bash
git add src/main/java/dev/nocs/imaging/ImagingService.java \
        src/test/java/dev/nocs/imaging/ImagingServiceTest.java
git commit -m "feat(imaging): ImagingService facade (submit/pause/resume/abort + bus bridge)"
```

---

### Task 14: Bean wiring in `AppBeansConfig`

**Files:**
- Modify: `src/main/java/dev/nocs/config/AppBeansConfig.java`

- [ ] **Step 14.1: Add the engine + strategy + config-derived beans**

Open `src/main/java/dev/nocs/config/AppBeansConfig.java` and add the following beans. Place them at the end of the class, next to the existing safety beans.

First, add the imports near the top:

```java
import dev.nocs.imaging.AutofocusStrategy;
import dev.nocs.imaging.DitherStrategy;
import dev.nocs.imaging.ImageAwait;
import dev.nocs.imaging.NoopAutofocusStrategy;
import dev.nocs.imaging.PixelOffsetDitherStrategy;
import dev.nocs.imaging.SequenceEngine;
import dev.nocs.platesolving.PlateSolvingService;
import dev.nocs.image.ImageStoreService;
import java.time.Duration;
```

Add these `@Bean` methods inside the `AppBeansConfig` class (copy-paste anywhere after the existing `safetyService(...)` bean; placement does not matter):

```java
    @Bean
    DitherStrategy ditherStrategy() {
        return new PixelOffsetDitherStrategy();
    }

    @Bean
    AutofocusStrategy autofocusStrategy(NocsProperties props) {
        String strategy = props.imaging() == null || props.imaging().autofocus() == null
                ? "noop"
                : props.imaging().autofocus().strategy();
        return switch (strategy.toLowerCase()) {
            case "noop" -> new NoopAutofocusStrategy();
            default -> throw new IllegalStateException(
                    "unknown nocs.imaging.autofocus.strategy: " + strategy
                            + " (v0.1 supports only 'noop'; 'sweep' is reserved for v0.2)");
        };
    }

    @Bean
    SequenceEngine sequenceEngine(
            dev.nocs.events.EventBus bus,
            ImageStoreService imageStore,
            ImageAwait imageAwait,
            DitherStrategy dither,
            AutofocusStrategy autofocus,
            PlateSolvingService solver,
            NocsProperties props) {
        NocsProperties.Imaging im = props.imaging() == null
                ? new NocsProperties.Imaging(null, null, null, null, null, null, null)
                : props.imaging();
        SequenceEngine.EngineConfig cfg = new SequenceEngine.EngineConfig(
                Duration.ofMillis(im.slewSettleMs()),
                im.syncThresholdArcmin(),
                Duration.ofSeconds(im.postSlewSolveTimeoutSec()),
                im.testExposureSec(),
                Duration.ofMillis(im.ditherSettleMs()),
                Duration.ofMillis(im.imageAwaitTimeoutMs()));
        return new SequenceEngine(bus, imageStore, imageAwait, dither, autofocus, solver, cfg);
    }
```

- [ ] **Step 14.2: Run — expect the full suite to still pass**

Run: `./gradlew test`
Expected: all tests pass (including `ImagingServiceTest`, `SequenceEngineTest`, `SlewAndSyncTest`).

- [ ] **Step 14.3: Commit**

```bash
git add src/main/java/dev/nocs/config/AppBeansConfig.java
git commit -m "feat(imaging): wire DitherStrategy, AutofocusStrategy, SequenceEngine beans"
```

---

### Task 15: `SequenceController` + REST round-trip test

**Files:**
- Create: `src/main/java/dev/nocs/imaging/api/SequenceController.java`
- Create: `src/test/java/dev/nocs/imaging/api/SequenceControllerTest.java`

- [ ] **Step 15.1: Write the failing test**

Create `src/test/java/dev/nocs/imaging/api/SequenceControllerTest.java`:

```java
package dev.nocs.imaging.api;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class SequenceControllerTest {

    @DynamicPropertySource
    static void tok(DynamicPropertyRegistry reg) {
        reg.add("nocs.auth.token", () -> "t");
    }

    @Autowired
    MockMvc mvc;
    @Autowired
    ObjectMapper mapper;

    @Test
    void rejectsMissingBearer() throws Exception {
        mvc.perform(post("/api/sequences").contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isUnauthorized());
        mvc.perform(get("/api/sequences"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void rejectsInvalidBody() throws Exception {
        mvc.perform(post("/api/sequences")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"target_id\":\"messier:M31\"}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void submitFailsFastWithNoDevicesAndReturns400() throws Exception {
        String body = "{\"target_id\":\"messier:M31\",\"steps\":[{\"filter\":\"L\",\"exposure_s\":1,\"count\":1}]}";
        mvc.perform(post("/api/sequences")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body))
                .andExpect(status().isBadRequest()); // no mount connected → SequenceSetupException
    }

    @Test
    void getUnknownIdReturns404() throws Exception {
        mvc.perform(get("/api/sequences/99999").header("Authorization", "Bearer t"))
                .andExpect(status().isNotFound());
    }
}
```

- [ ] **Step 15.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.imaging.api.SequenceControllerTest'`
Expected: compile failure.

- [ ] **Step 15.3: Implement `SequenceController`**

Create `src/main/java/dev/nocs/imaging/api/SequenceController.java`:

```java
package dev.nocs.imaging.api;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.nocs.imaging.ImagingService;
import dev.nocs.imaging.SequenceDefinition;
import dev.nocs.imaging.SequenceRepository;
import dev.nocs.imaging.SequenceRun;
import dev.nocs.imaging.SequenceSetupException;
import dev.nocs.imaging.api.dto.AbortRequest;
import dev.nocs.imaging.api.dto.SequenceDefinitionDto;
import dev.nocs.imaging.api.dto.SequenceView;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/sequences")
public class SequenceController {

    private final ImagingService imaging;
    private final ObjectMapper mapper;

    public SequenceController(ImagingService imaging, ObjectMapper mapper) {
        this.imaging = imaging;
        this.mapper = mapper;
    }

    @PostMapping
    public ResponseEntity<SequenceView> submit(@RequestBody SequenceDefinitionDto dto) {
        if (dto == null) {
            throw new IllegalArgumentException("body required");
        }
        SequenceDefinition def = dto.toDomain();
        long id = imaging.submit(def);
        SequenceRun run = imaging.find(id).orElseThrow();
        return ResponseEntity.status(HttpStatus.CREATED).body(SequenceView.from(run, mapper));
    }

    @GetMapping
    public List<SequenceView> list(
            @RequestParam(value = "session_id", required = false) Long sessionId,
            @RequestParam(value = "limit", defaultValue = "50") int limit,
            @RequestParam(value = "offset", defaultValue = "0") int offset) {
        return imaging.list(new SequenceRepository.Filters(sessionId, limit, offset))
                .stream().map(r -> SequenceView.from(r, mapper)).toList();
    }

    @GetMapping("/{id}")
    public ResponseEntity<SequenceView> get(@PathVariable long id) {
        return imaging.find(id)
                .map(r -> ResponseEntity.ok(SequenceView.from(r, mapper)))
                .orElse(ResponseEntity.notFound().build());
    }

    @PostMapping("/{id}/pause")
    public Map<String, String> pause(@PathVariable long id) {
        imaging.pause(id);
        return Map.of("status", "ok");
    }

    @PostMapping("/{id}/resume")
    public Map<String, String> resume(@PathVariable long id) {
        imaging.resume(id);
        return Map.of("status", "ok");
    }

    @PostMapping("/{id}/abort")
    public Map<String, String> abort(
            @PathVariable long id, @RequestBody(required = false) AbortRequest req) {
        imaging.abort(id, req == null ? null : req.reason());
        return Map.of("status", "ok");
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, String>> badRequest(IllegalArgumentException e) {
        return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
    }

    @ExceptionHandler(SequenceSetupException.class)
    public ResponseEntity<Map<String, String>> setup(SequenceSetupException e) {
        return ResponseEntity.badRequest().body(Map.of(
                "error", e.getMessage(),
                "kind", e.kind().name()));
    }

    @ExceptionHandler(IllegalStateException.class)
    public ResponseEntity<Map<String, String>> conflict(IllegalStateException e) {
        return ResponseEntity.status(HttpStatus.CONFLICT).body(Map.of("error", e.getMessage()));
    }
}
```

- [ ] **Step 15.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.imaging.api.SequenceControllerTest'`
Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 15.5: Commit**

```bash
git add src/main/java/dev/nocs/imaging/api/SequenceController.java \
        src/test/java/dev/nocs/imaging/api/SequenceControllerTest.java
git commit -m "feat(imaging): SequenceController REST endpoints (/api/sequences/*)"
```

---

### Task 16: End-to-end happy-path integration test

**Files:**
- Create: `src/test/java/dev/nocs/imaging/IntegrationHappyPathSequenceTest.java`
- Create: `src/test/java/dev/nocs/imaging/FakeDeviceFixture.java`

This task introduces a shared fixture (`FakeDeviceFixture`) that registers connected fake mount/camera/filter-wheel/focuser in the `DeviceRegistry`. It also registers a fake `PlateSolvingService` via a `@TestConfiguration`.

- [ ] **Step 16.1: Write the fixture**

Create `src/test/java/dev/nocs/imaging/FakeDeviceFixture.java`:

```java
package dev.nocs.imaging;

import dev.nocs.device.Camera;
import dev.nocs.device.CameraState;
import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceKind;
import dev.nocs.device.DeviceRegistry;
import dev.nocs.device.FilterWheel;
import dev.nocs.device.FilterWheelState;
import dev.nocs.device.Focuser;
import dev.nocs.device.FocuserState;
import dev.nocs.device.Mount;
import dev.nocs.device.MountState;
import dev.nocs.image.ImageStoreService;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

public final class FakeDeviceFixture {

    public final FakeMount mount = new FakeMount();
    public final FakeCamera camera;
    public final FakeWheel wheel = new FakeWheel();
    public final FakeFocuser focuser = new FakeFocuser();

    public FakeDeviceFixture(ImageStoreService store) {
        this.camera = new FakeCamera(store);
    }

    public void registerAndConnect(DeviceRegistry reg) {
        reg.add(mount); reg.add(camera); reg.add(wheel); reg.add(focuser);
        mount.connect(); camera.connect(); wheel.connect(); focuser.connect();
    }

    public void deregister(DeviceRegistry reg) {
        reg.remove(mount.id()); reg.remove(camera.id()); reg.remove(wheel.id()); reg.remove(focuser.id());
    }

    public static final class FakeMount implements Mount {
        public final AtomicInteger slewCalls = new AtomicInteger();
        public final AtomicInteger syncCalls = new AtomicInteger();
        public final AtomicInteger parkCalls = new AtomicInteger();
        public final AtomicInteger eStopCalls = new AtomicInteger();
        private MountState s = MountState.DISCONNECTED;
        public DeviceId id() { return new DeviceId("itest-mount"); }
        public String indiName() { return "itest-mount"; }
        public DeviceKind kind() { return DeviceKind.MOUNT; }
        public boolean isConnected() { return s != MountState.DISCONNECTED; }
        public void connect() { s = MountState.IDLE; }
        public void disconnect() { s = MountState.DISCONNECTED; }
        public MountState state() { return s; }
        public void slew(double r, double d) { slewCalls.incrementAndGet(); s = MountState.TRACKING; }
        public void syncTo(double r, double d) { syncCalls.incrementAndGet(); }
        public void park() { parkCalls.incrementAndGet(); s = MountState.PARKED; }
        public void unpark() { s = MountState.IDLE; }
        public void abort() {}
        @Override public void emergencyStop() { eStopCalls.incrementAndGet(); s = MountState.E_STOPPED; }
        @Override public void resetEStop() { if (s == MountState.E_STOPPED) s = MountState.IDLE; }
    }

    public static final class FakeCamera implements Camera {
        private final ImageStoreService store;
        public final AtomicInteger exposures = new AtomicInteger();
        public final AtomicInteger aborts = new AtomicInteger();
        public final AtomicInteger eStopCalls = new AtomicInteger();
        private volatile boolean eStopped = false;
        FakeCamera(ImageStoreService s) { this.store = s; }
        public DeviceId id() { return new DeviceId("itest-camera"); }
        public String indiName() { return "itest-camera"; }
        public DeviceKind kind() { return DeviceKind.CAMERA; }
        public boolean isConnected() { return !eStopped; }
        public void connect() {}
        public void disconnect() {}
        public CameraState state() { return eStopped ? CameraState.E_STOPPED : CameraState.IDLE; }
        public void cool(double x) {}
        public void expose(double s) {
            if (eStopped) {
                throw new RuntimeException("camera is E_STOPPED");
            }
            exposures.incrementAndGet();
            Thread.ofVirtual().start(() -> {
                try { Thread.sleep(40); } catch (InterruptedException ignored) {}
                if (eStopped) return;
                store.accept(id(), dev.nocs.image.MiniFits.oneByOneZero(), ".fits");
            });
        }
        public void abortExposure() { aborts.incrementAndGet(); }
        public Double currentTemperatureCelsius() { return null; }
        @Override public void emergencyStop() { eStopCalls.incrementAndGet(); eStopped = true; }
        @Override public void resetEStop() { eStopped = false; }
    }

    public static final class FakeWheel implements FilterWheel {
        private FilterWheelState s = FilterWheelState.DISCONNECTED;
        private int slot = 1;
        public DeviceId id() { return new DeviceId("itest-wheel"); }
        public String indiName() { return "itest-wheel"; }
        public DeviceKind kind() { return DeviceKind.FILTERWHEEL; }
        public boolean isConnected() { return s != FilterWheelState.DISCONNECTED; }
        public void connect() { s = FilterWheelState.IDLE; }
        public void disconnect() { s = FilterWheelState.DISCONNECTED; }
        public FilterWheelState state() { return s; }
        public List<String> slotNames() { return List.of("L", "R", "G", "B"); }
        public int currentSlot() { return slot; }
        public void selectSlot(int slotNumber) { slot = slotNumber; }
    }

    public static final class FakeFocuser implements Focuser {
        private FocuserState s = FocuserState.DISCONNECTED;
        public DeviceId id() { return new DeviceId("itest-focuser"); }
        public String indiName() { return "itest-focuser"; }
        public DeviceKind kind() { return DeviceKind.FOCUSER; }
        public boolean isConnected() { return s != FocuserState.DISCONNECTED; }
        public void connect() { s = FocuserState.IDLE; }
        public void disconnect() { s = FocuserState.DISCONNECTED; }
        public FocuserState state() { return s; }
        public int currentPosition() { return 25_000; }
        public void moveAbsolute(int p) {}
        public void moveRelative(int d) {}
        public void abort() {}
    }
}
```

- [ ] **Step 16.2: Write the failing happy-path test**

Create `src/test/java/dev/nocs/imaging/IntegrationHappyPathSequenceTest.java`:

```java
package dev.nocs.imaging;

import dev.nocs.device.DeviceService;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.image.ImageStoreService;
import dev.nocs.platesolving.FailureKind;
import dev.nocs.platesolving.PlateSolution;
import dev.nocs.platesolving.PlateSolvingService;
import dev.nocs.platesolving.SolveOptions;
import dev.nocs.platesolving.SolveOutcome;
import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.CopyOnWriteArrayList;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.http.MediaType;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import reactor.core.Disposable;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class IntegrationHappyPathSequenceTest {

    @DynamicPropertySource
    static void props(DynamicPropertyRegistry reg) {
        reg.add("nocs.auth.token", () -> "t");
        reg.add("nocs.imaging.image-await-timeout-ms", () -> "10000");
        reg.add("nocs.imaging.slew-settle-ms", () -> "50");
    }

    @TestConfiguration
    static class FakeSolverConfig {
        @Bean
        @Primary
        PlateSolvingService fakeSolver() {
            PlateSolution sol = new PlateSolution(
                    10.684166, 41.269166, 1.5, 0, 1, 1, Instant.now(), "fake");
            return new PlateSolvingService() {
                public SolveOutcome solve(byte[] fits, SolveOptions options) {
                    return new SolveOutcome.Solved(sol, 5L);
                }
                public boolean isAvailable() { return true; }
            };
        }
    }

    @Autowired
    MockMvc mvc;
    @Autowired
    DeviceService deviceService;
    @Autowired
    EventBus bus;
    @Autowired
    ImageStoreService imageStore;

    private FakeDeviceFixture fx;
    private Disposable sub;
    private final CopyOnWriteArrayList<Event> seen = new CopyOnWriteArrayList<>();

    @BeforeEach
    void setUp() {
        fx = new FakeDeviceFixture(imageStore);
        fx.registerAndConnect(deviceService.registry());
        sub = bus.subscribeAll().subscribe(seen::add);
    }

    @AfterEach
    void tearDown() {
        sub.dispose();
        fx.deregister(deviceService.registry());
    }

    @Test
    void runsTwoStepsToCompletion() throws Exception {
        String body = """
                {
                  "name":"m31-mini",
                  "target_id":"messier:M31",
                  "dither":{"enabled":true,"pixels":5,"every_n_subs":1},
                  "pre_steps":[{"type":"slew_and_sync"},{"type":"autofocus"}],
                  "steps":[
                    {"filter":"L","exposure_s":0.2,"count":2},
                    {"filter":"R","exposure_s":0.2,"count":1}
                  ]
                }
                """;

        String response = mvc.perform(post("/api/sequences")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body))
                .andExpect(status().isCreated())
                .andReturn().getResponse().getContentAsString();

        long id = extractId(response);

        Awaitility.await().atMost(Duration.ofSeconds(30)).untilAsserted(() -> {
            var status = mvc.perform(get("/api/sequences/" + id)
                    .header("Authorization", "Bearer t")).andReturn().getResponse().getContentAsString();
            assertThat(status).contains("\"status\":\"COMPLETED\"");
        });

        assertThat(seen).anyMatch(e -> e.topic() == Topic.SEQUENCE && "sequence_started".equals(e.type()));
        assertThat(seen).anyMatch(e -> e.topic() == Topic.SEQUENCE && "sequence_completed".equals(e.type()));
        assertThat(seen).anyMatch(e -> e.topic() == Topic.SEQUENCE && "autofocus_completed".equals(e.type()));
        assertThat(seen.stream()
                .filter(e -> e.topic() == Topic.SEQUENCE && "sub_completed".equals(e.type()))
                .count()).isEqualTo(3);
        assertThat(fx.camera.exposures.get()).isGreaterThanOrEqualTo(3); // plus 1 for prestep test exposure
        assertThat(fx.mount.slewCalls.get()).isGreaterThanOrEqualTo(1);
    }

    private static long extractId(String json) {
        int i = json.indexOf("\"id\":");
        int start = i + 5;
        int end = start;
        while (end < json.length() && Character.isDigit(json.charAt(end))) end++;
        return Long.parseLong(json.substring(start, end));
    }
}
```

- [ ] **Step 16.3: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.imaging.IntegrationHappyPathSequenceTest'`
Expected: `BUILD SUCCESSFUL`. (This test boots the full Spring context; expect 15–30 s.)

- [ ] **Step 16.4: Commit**

```bash
git add src/test/java/dev/nocs/imaging/FakeDeviceFixture.java \
        src/test/java/dev/nocs/imaging/IntegrationHappyPathSequenceTest.java
git commit -m "test(imaging): end-to-end happy-path sequence integration test"
```

---

### Task 17: Pause / resume integration test

**Files:**
- Create: `src/test/java/dev/nocs/imaging/IntegrationPauseResumeSequenceTest.java`

- [ ] **Step 17.1: Write the test**

Create `src/test/java/dev/nocs/imaging/IntegrationPauseResumeSequenceTest.java`:

```java
package dev.nocs.imaging;

import dev.nocs.device.DeviceService;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.image.ImageStoreService;
import dev.nocs.platesolving.PlateSolution;
import dev.nocs.platesolving.PlateSolvingService;
import dev.nocs.platesolving.SolveOptions;
import dev.nocs.platesolving.SolveOutcome;
import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.CopyOnWriteArrayList;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.http.MediaType;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import reactor.core.Disposable;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class IntegrationPauseResumeSequenceTest {

    @DynamicPropertySource
    static void props(DynamicPropertyRegistry reg) {
        reg.add("nocs.auth.token", () -> "t");
        reg.add("nocs.imaging.image-await-timeout-ms", () -> "10000");
    }

    @TestConfiguration
    static class Cfg {
        @Bean @Primary
        PlateSolvingService fakeSolver() {
            PlateSolution sol = new PlateSolution(
                    10.684, 41.269, 1.5, 0, 1, 1, Instant.now(), "fake");
            return new PlateSolvingService() {
                public SolveOutcome solve(byte[] fits, SolveOptions o) { return new SolveOutcome.Solved(sol, 5L); }
                public boolean isAvailable() { return true; }
            };
        }
    }

    @Autowired MockMvc mvc;
    @Autowired DeviceService deviceService;
    @Autowired EventBus bus;
    @Autowired ImageStoreService imageStore;

    private FakeDeviceFixture fx;
    private Disposable sub;
    private final CopyOnWriteArrayList<Event> seen = new CopyOnWriteArrayList<>();

    @BeforeEach
    void setUp() {
        fx = new FakeDeviceFixture(imageStore);
        fx.registerAndConnect(deviceService.registry());
        sub = bus.subscribeAll().subscribe(seen::add);
    }

    @AfterEach
    void tearDown() {
        sub.dispose();
        fx.deregister(deviceService.registry());
    }

    @Test
    void pauseAfterFirstSubThenResumeRunsToCompletion() throws Exception {
        String body = """
                {
                  "name":"pause-resume",
                  "target_id":"messier:M31",
                  "dither":{"enabled":false,"pixels":0,"every_n_subs":1},
                  "pre_steps":[],
                  "steps":[{"filter":"L","exposure_s":0.3,"count":3}]
                }
                """;
        long id = extractId(mvc.perform(post("/api/sequences")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isCreated())
                .andReturn().getResponse().getContentAsString());

        Awaitility.await().atMost(Duration.ofSeconds(10)).until(() ->
                seen.stream().anyMatch(e -> e.topic() == Topic.SEQUENCE && "sub_completed".equals(e.type())));

        mvc.perform(post("/api/sequences/" + id + "/pause")
                .header("Authorization", "Bearer t")).andExpect(status().isOk());

        Awaitility.await().atMost(Duration.ofSeconds(5)).until(() ->
                mvc.perform(get("/api/sequences/" + id).header("Authorization", "Bearer t"))
                        .andReturn().getResponse().getContentAsString().contains("\"status\":\"PAUSED\""));

        int completedBeforeResume = (int) seen.stream()
                .filter(e -> e.topic() == Topic.SEQUENCE && "sub_completed".equals(e.type())).count();

        mvc.perform(post("/api/sequences/" + id + "/resume")
                .header("Authorization", "Bearer t")).andExpect(status().isOk());

        Awaitility.await().atMost(Duration.ofSeconds(30)).untilAsserted(() -> {
            var s = mvc.perform(get("/api/sequences/" + id).header("Authorization", "Bearer t"))
                    .andReturn().getResponse().getContentAsString();
            assertThat(s).contains("\"status\":\"COMPLETED\"");
        });

        int completedAfter = (int) seen.stream()
                .filter(e -> e.topic() == Topic.SEQUENCE && "sub_completed".equals(e.type())).count();
        assertThat(completedAfter).isEqualTo(3);
        assertThat(completedAfter).isGreaterThan(completedBeforeResume);
        assertThat(seen).anyMatch(e -> e.topic() == Topic.SEQUENCE && "sequence_paused".equals(e.type()));
        assertThat(seen).anyMatch(e -> e.topic() == Topic.SEQUENCE && "sequence_resumed".equals(e.type()));
    }

    private static long extractId(String json) {
        int i = json.indexOf("\"id\":");
        int start = i + 5;
        int end = start;
        while (end < json.length() && Character.isDigit(json.charAt(end))) end++;
        return Long.parseLong(json.substring(start, end));
    }
}
```

- [ ] **Step 17.2: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.imaging.IntegrationPauseResumeSequenceTest'`
Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 17.3: Commit**

```bash
git add src/test/java/dev/nocs/imaging/IntegrationPauseResumeSequenceTest.java
git commit -m "test(imaging): pause + resume mid-sequence integration test"
```

---

### Task 18: Safety-rule-triggered abort + e-stop integration tests

**Files:**
- Create: `src/test/java/dev/nocs/imaging/IntegrationRuleAbortSequenceTest.java`
- Create: `src/test/java/dev/nocs/imaging/IntegrationEStopSequenceTest.java`
- Create: `src/test/resources/imaging/rules-abort.yaml`
- Create: `src/test/resources/imaging/rules-estop.yaml`

- [ ] **Step 18.1: Write the fixture YAML files**

Create `src/test/resources/imaging/rules-abort.yaml`:

```yaml
rules:
  - name: rain
    when: { rain_detected: true }
    then: abort_and_park
```

Create `src/test/resources/imaging/rules-estop.yaml`:

```yaml
rules:
  - name: rain
    when: { rain_detected: true }
    then: e_stop
```

- [ ] **Step 18.2: Write the rule-abort test**

Create `src/test/java/dev/nocs/imaging/IntegrationRuleAbortSequenceTest.java`:

```java
package dev.nocs.imaging;

import dev.nocs.device.DeviceService;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.image.ImageStoreService;
import dev.nocs.platesolving.PlateSolution;
import dev.nocs.platesolving.PlateSolvingService;
import dev.nocs.platesolving.SolveOptions;
import dev.nocs.platesolving.SolveOutcome;
import dev.nocs.safety.SafetyService;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.CopyOnWriteArrayList;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.http.MediaType;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import reactor.core.Disposable;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class IntegrationRuleAbortSequenceTest {

    @TempDir
    static Path tmp;

    @DynamicPropertySource
    static void props(DynamicPropertyRegistry reg) throws Exception {
        Path rules = tmp.resolve("rules-abort.yaml");
        Files.writeString(rules,
                """
                rules:
                  - name: rain
                    when: { rain_detected: true }
                    then: abort_and_park
                """);
        reg.add("nocs.auth.token", () -> "t");
        reg.add("nocs.safety.rules-path", () -> rules.toString());
        reg.add("nocs.imaging.image-await-timeout-ms", () -> "10000");
    }

    @TestConfiguration
    static class Cfg {
        @Bean @Primary
        PlateSolvingService fakeSolver() {
            PlateSolution sol = new PlateSolution(10.684, 41.269, 1.5, 0, 1, 1, Instant.now(), "fake");
            return new PlateSolvingService() {
                public SolveOutcome solve(byte[] b, SolveOptions o) { return new SolveOutcome.Solved(sol, 5L); }
                public boolean isAvailable() { return true; }
            };
        }
    }

    @Autowired MockMvc mvc;
    @Autowired DeviceService deviceService;
    @Autowired EventBus bus;
    @Autowired ImageStoreService imageStore;
    @Autowired SafetyService safety;

    private FakeDeviceFixture fx;
    private Disposable sub;
    private final CopyOnWriteArrayList<Event> seen = new CopyOnWriteArrayList<>();

    @BeforeEach
    void setUp() {
        safety.reload();
        safety.reset("test-setup");
        fx = new FakeDeviceFixture(imageStore);
        fx.registerAndConnect(deviceService.registry());
        sub = bus.subscribeAll().subscribe(seen::add);
    }

    @AfterEach
    void tearDown() {
        sub.dispose();
        fx.deregister(deviceService.registry());
    }

    @Test
    void rainRuleAbortsRunningSequenceAndParksMount() throws Exception {
        String body = """
                {
                  "name":"rule-abort",
                  "target_id":"messier:M31",
                  "dither":{"enabled":false,"pixels":0,"every_n_subs":1},
                  "pre_steps":[],
                  "steps":[{"filter":"L","exposure_s":0.5,"count":5}]
                }
                """;
        long id = extractId(mvc.perform(post("/api/sequences")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isCreated())
                .andReturn().getResponse().getContentAsString());

        Awaitility.await().atMost(Duration.ofSeconds(10)).until(() ->
                seen.stream().anyMatch(e -> e.topic() == Topic.SEQUENCE && "sub_completed".equals(e.type())));

        mvc.perform(post("/api/safety/sensors/readings")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"sensor\":\"weather\",\"values\":{\"rain_detected\":true}}"))
                .andExpect(status().isOk());

        Awaitility.await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> {
            var s = mvc.perform(get("/api/sequences/" + id).header("Authorization", "Bearer t"))
                    .andReturn().getResponse().getContentAsString();
            assertThat(s).contains("\"status\":\"ABORTED\"");
        });

        assertThat(fx.mount.parkCalls.get()).isGreaterThanOrEqualTo(1);
        assertThat(seen).anyMatch(e -> e.topic() == Topic.SEQUENCE
                && "sequence_aborted".equals(e.type())
                && String.valueOf(e.payload().get("reason")).contains("rule:rain"));
    }

    private static long extractId(String json) {
        int i = json.indexOf("\"id\":");
        int start = i + 5;
        int end = start;
        while (end < json.length() && Character.isDigit(json.charAt(end))) end++;
        return Long.parseLong(json.substring(start, end));
    }
}
```

- [ ] **Step 18.3: Write the e-stop test**

Create `src/test/java/dev/nocs/imaging/IntegrationEStopSequenceTest.java`:

```java
package dev.nocs.imaging;

import dev.nocs.device.DeviceService;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.image.ImageStoreService;
import dev.nocs.platesolving.PlateSolution;
import dev.nocs.platesolving.PlateSolvingService;
import dev.nocs.platesolving.SolveOptions;
import dev.nocs.platesolving.SolveOutcome;
import dev.nocs.safety.SafetyService;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.CopyOnWriteArrayList;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.http.MediaType;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import reactor.core.Disposable;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class IntegrationEStopSequenceTest {

    @TempDir
    static Path tmp;

    @DynamicPropertySource
    static void props(DynamicPropertyRegistry reg) throws Exception {
        Path rules = tmp.resolve("rules-estop.yaml");
        Files.writeString(rules,
                """
                rules:
                  - name: rain
                    when: { rain_detected: true }
                    then: e_stop
                """);
        reg.add("nocs.auth.token", () -> "t");
        reg.add("nocs.safety.rules-path", () -> rules.toString());
        reg.add("nocs.imaging.image-await-timeout-ms", () -> "10000");
    }

    @TestConfiguration
    static class Cfg {
        @Bean @Primary
        PlateSolvingService fakeSolver() {
            PlateSolution sol = new PlateSolution(10.684, 41.269, 1.5, 0, 1, 1, Instant.now(), "fake");
            return new PlateSolvingService() {
                public SolveOutcome solve(byte[] b, SolveOptions o) { return new SolveOutcome.Solved(sol, 5L); }
                public boolean isAvailable() { return true; }
            };
        }
    }

    @Autowired MockMvc mvc;
    @Autowired DeviceService deviceService;
    @Autowired EventBus bus;
    @Autowired ImageStoreService imageStore;
    @Autowired SafetyService safety;

    private FakeDeviceFixture fx;
    private Disposable sub;
    private final CopyOnWriteArrayList<Event> seen = new CopyOnWriteArrayList<>();

    @BeforeEach
    void setUp() {
        safety.reload();
        safety.reset("test-setup");
        fx = new FakeDeviceFixture(imageStore);
        fx.registerAndConnect(deviceService.registry());
        sub = bus.subscribeAll().subscribe(seen::add);
    }

    @AfterEach
    void tearDown() {
        sub.dispose();
        fx.deregister(deviceService.registry());
    }

    @Test
    void eStopRuleAbortsRunAndEmergencyStopsDevices() throws Exception {
        String body = """
                {
                  "name":"rule-estop",
                  "target_id":"messier:M31",
                  "dither":{"enabled":false,"pixels":0,"every_n_subs":1},
                  "pre_steps":[],
                  "steps":[{"filter":"L","exposure_s":0.5,"count":5}]
                }
                """;
        long id = extractId(mvc.perform(post("/api/sequences")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isCreated())
                .andReturn().getResponse().getContentAsString());

        Awaitility.await().atMost(Duration.ofSeconds(10)).until(() ->
                seen.stream().anyMatch(e -> e.topic() == Topic.SEQUENCE && "sub_completed".equals(e.type())));

        mvc.perform(post("/api/safety/sensors/readings")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"sensor\":\"weather\",\"values\":{\"rain_detected\":true}}"))
                .andExpect(status().isOk());

        Awaitility.await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> {
            var s = mvc.perform(get("/api/sequences/" + id).header("Authorization", "Bearer t"))
                    .andReturn().getResponse().getContentAsString();
            assertThat(s).contains("\"status\":\"ABORTED\"");
        });

        assertThat(fx.mount.parkCalls.get()).isGreaterThanOrEqualTo(1);
        assertThat(fx.mount.eStopCalls.get()).isGreaterThanOrEqualTo(1);
        assertThat(fx.camera.aborts.get()).isGreaterThanOrEqualTo(1);
        assertThat(fx.camera.eStopCalls.get()).isGreaterThanOrEqualTo(1);
        assertThat(seen).anyMatch(e -> e.topic() == Topic.SAFETY && "e_stopped".equals(e.type()));
    }

    private static long extractId(String json) {
        int i = json.indexOf("\"id\":");
        int start = i + 5;
        int end = start;
        while (end < json.length() && Character.isDigit(json.charAt(end))) end++;
        return Long.parseLong(json.substring(start, end));
    }
}
```

- [ ] **Step 18.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.imaging.IntegrationRuleAbortSequenceTest' --tests 'dev.nocs.imaging.IntegrationEStopSequenceTest'`
Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 18.5: Run the whole Plan G test subset as a smoke check**

Run: `./gradlew test --tests 'dev.nocs.imaging.*'`
Expected: all imaging tests pass.

- [ ] **Step 18.6: Commit**

```bash
git add src/test/java/dev/nocs/imaging/IntegrationRuleAbortSequenceTest.java \
        src/test/java/dev/nocs/imaging/IntegrationEStopSequenceTest.java \
        src/test/resources/imaging/
git commit -m "test(imaging): rule-triggered abort + e-stop mid-sequence integration tests"
```

---

### Task 19: Docs — decomposition + README

**Files:**
- Modify: `docs/superpowers/plans/2026-04-22-v0.1-plan-decomposition.md`
- Modify: `README.md`

- [ ] **Step 19.1: Update the decomposition status table**

In `docs/superpowers/plans/2026-04-22-v0.1-plan-decomposition.md`, change the Plan G row in the "Plan overview" and "Current status" tables.

Replace the `| **G** | ... | Simulated end-to-end sequence: pre-steps, filter loop, dither, pause/abort/e-stop integration. |` row so that the demoable end state references the written plan file:

```markdown
| **G** | ImagingService / sequence engine | B, C, D, E, F | Simulated end-to-end sequence: pre-steps, filter loop, dither, pause/abort/e-stop integration. Implemented: [2026-04-22-nocs-imaging-sequence-engine.md](./2026-04-22-nocs-imaging-sequence-engine.md). |
```

In the "Current status" table, replace the `| G, H | No | ...` row with two rows:

```markdown
| G | Yes | [2026-04-22-nocs-imaging-sequence-engine.md](./2026-04-22-nocs-imaging-sequence-engine.md) |
| H | No | Author with the `writing-plans` skill when starting that slice |
```

- [ ] **Step 19.2: Add a "Sequences" section to `README.md`**

Append the following section to `README.md` (before the "Project layout" or equivalent end-matter; placement is a judgment call — put it after the existing plate-solving section).

```markdown
## Sequences (Plan G)

NOCS v0.1 ships a minimal sequence engine. Submit a JSON definition and watch it run
end-to-end against your connected mount / camera / filter wheel / focuser. The engine
honours `SafetyService` pause + abort + e-stop bus events, so a rain-detected sensor
reading while a run is live will park the mount and abort the sequence.

```bash
TOKEN=$(awk '/token:/ {print $2}' "$NOCS_DATA_DIR/config.yaml")
curl -sS -X POST http://127.0.0.1:8080/api/sequences \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "name":"m31-test",
           "target_id":"messier:M31",
           "dither":{"enabled":true,"pixels":10,"every_n_subs":1},
           "pre_steps":[{"type":"slew_and_sync"},{"type":"autofocus"}],
           "steps":[
             {"filter":"L","exposure_s":120,"count":3},
             {"filter":"R","exposure_s":180,"count":2}
           ]
         }'

# Follow progress over SSE (Ctrl-C to stop):
curl -N -H "Authorization: Bearer $TOKEN" \
     "http://127.0.0.1:8080/api/events?topics=sequence,camera,mount,safety"

# Pause / resume / abort by id:
curl -sS -X POST http://127.0.0.1:8080/api/sequences/1/pause  -H "Authorization: Bearer $TOKEN"
curl -sS -X POST http://127.0.0.1:8080/api/sequences/1/resume -H "Authorization: Bearer $TOKEN"
curl -sS -X POST http://127.0.0.1:8080/api/sequences/1/abort  -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" -d '{"reason":"clouds"}'
```

Notes:

- Autofocus in v0.1 is the `noop` strategy (it emits events but does not touch the focuser). A real HFR hill-climb is planned for v0.2; the seam is the `AutofocusStrategy` bean in `AppBeansConfig`.
- Dithering uses the pixel scale from the most recent plate solve; the first few subs before a solve exists will emit `dither_skipped`.
- One sequence runs at a time. A second `POST /api/sequences` while one is `RUNNING` or `PAUSED` returns `409 Conflict`.
- Saved FITS and thumbnails follow the layout documented in the ImageStore plan (Plan D).
```

- [ ] **Step 19.3: Run the full test suite**

Run: `./gradlew test`
Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 19.4: Commit**

```bash
git add docs/superpowers/plans/2026-04-22-v0.1-plan-decomposition.md README.md
git commit -m "docs: Plan G plan file, README sequences section, decomposition status"
```

---

## Post-implementation checklist

After Task 19, verify the following from a fresh shell, against the in-memory test profile:

1. `./gradlew test` — green. ImagingService, SequenceEngine, REST controller, and all four integration tests pass.
2. `./gradlew bootRun` — the server starts; `POST /api/sequences` with no devices returns `400` with `kind: MISSING_DEVICE`.
3. With the INDI simulator drivers wired in `config.yaml` (see Plan B) and after connecting the devices via `/api/devices/.../connect`, submit the example sequence from the README. Watch `/api/events?topics=sequence,camera,mount` and confirm the run reaches `sequence_completed` with three saved FITS visible under `/api/images`.
4. Trigger the rain rule via `POST /api/safety/sensors/readings` mid-sequence and confirm the run transitions to `ABORTED`, the mount receives `park`, and (for the `e_stop` rule) the camera's `emergencyStop` is invoked.

These four confirmations are the spec §1 success criteria #4–#6 exercised against the simulator.

## Open items deferred to v0.2 (not this plan)

- Real autofocus (HFR sweep + hill climb) — see `AutofocusStrategy` seam.
- Re-autofocus between filter changes — spec §10.2 reserved flag.
- Guider feedback during dithers — Plan on a `GuidingService` + dither feedback seam in v0.2.
- Between-sub plate-solve + recenter (drift correction) — re-use the `SlewAndSync` helper with an offset input.
- Web UI for sequence editor + runner (Plan H).
- Per-session sequence history UI (Plan H).
