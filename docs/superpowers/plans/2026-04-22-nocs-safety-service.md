# NOCS SafetyService Implementation Plan (Plan F)

> **See also:** [NOCS v0.1 plan decomposition (A–I)](./2026-04-22-v0.1-plan-decomposition.md) — full roadmap and dependencies.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the `SafetyService` backplane: a YAML-defined rule engine driven by sensor readings + the active target, an always-available `POST /api/safety/e-stop` that aborts in-flight exposures, parks every connected mount, and transitions affected devices to `E_STOPPED`, plus the supporting REST surface (`GET /api/safety/rules`, `POST /api/safety/rules/reload`, `POST /api/safety/reset`, `POST /api/safety/sensors/readings`, `POST /api/safety/active-target`). After this plan, the v0.1 success criterion "trigger a configured safety rule and observe the mount park and the sequence abort" can be exercised via curl + the INDI simulator (or a unit-test fake), with no sequence engine required yet.

**Architecture:** `SafetyService` owns three collaborators: a pure `SafetyRuleEngine` that evaluates a `SafetyState` snapshot against the loaded rules, a `SafetyActionDispatcher` that turns triggered actions into device commands + bus events, and a `SafetyRuleParser` that loads rules from `safety.yaml` (one rule = one condition + one action). Sensor readings arrive via either `POST /api/safety/sensors/readings` or the new `Topic.SENSOR` bus topic — both paths land in the same `SafetyService.onReading(SensorReading)` method. The active target arrives via `POST /api/safety/active-target` or a `SEQUENCE/target_active` bus event; an `@Scheduled` task recomputes its altitude every `nocs.safety.altitude-eval-interval-ms` and re-evaluates `altitude_below` rules. Each rule is latched: once `ACTIVE`, it does not re-fire until the underlying condition clears (or `POST /api/safety/reset` is called). E-stop is a privileged path that bypasses the rule engine and runs the dispatcher's `e_stop` directly. Device-level E-stop is enforced inside the adapters: while `state == E_STOPPED`, command methods throw `DeviceEStoppedException` until `resetEStop()` is called.

**Tech Stack:**
- JDK 25 + Spring Boot 3.5 (from Plan A)
- `jackson-dataformat-yaml` (already on classpath — see `build.gradle.kts`) for `safety.yaml`
- Project Reactor `EventBus` (from Plan A) for SAFETY/SENSOR/SEQUENCE topics
- `@EnableScheduling` + `@Scheduled` for the altitude evaluator
- JUnit 5, AssertJ, Spring `MockMvc`, Awaitility (already present)

## Scope

### In scope for Plan F

1. New bus topic `SENSOR`. `SAFETY` already exists in `events/Topic.java`; Plan F is its first publisher.
2. New config block `nocs.safety.*`: `rules-path`, `altitude-eval-interval-ms`, `sensor-offline-default-seconds`.
3. Bundled `safety.example.yaml` (three example rules per spec §6.1) plus copy-on-first-run via `DataDirBootstrap`.
4. YAML rule loader for the v0.1 fixed vocabulary:
   - Conditions: `humidity_above`, `rain_detected`, `altitude_below`, `sensor_offline`.
   - Actions: `pause_sequence`, `abort_and_park`, `e_stop`.
5. Pure `SafetyRuleEngine` that evaluates a `SafetyState` snapshot; latched per-rule (idempotent re-fire).
6. `SafetyActionDispatcher` effects (spec §6.3):
   - `e_stop`: every connected camera `abortExposure()` + `emergencyStop()`; every connected mount `park()` + `emergencyStop()`; publish `SEQUENCE/abort_requested {reason:"e_stop", caller}`; publish `SAFETY/e_stopped` (priority high, payload includes `reason`); log via `SessionService` if a session is open.
   - `abort_and_park`: publish `SEQUENCE/abort_requested {reason:"rule:<name>"}` + park every connected mount.
   - `pause_sequence`: publish `SEQUENCE/pause_requested {reason:"rule:<name>"}` only.
7. Device E-stop surface:
   - `Device#emergencyStop()` and `Device#resetEStop()` defaults on the interface (no-ops by default).
   - `Mount` and `Camera` document the contract; `IndiMountAdapter` / `IndiCameraAdapter` override them, transition to `E_STOPPED`, and gate every command method behind a `DeviceEStoppedException` guard.
   - `FilterWheel` / `Focuser` keep the default no-op (their state machines in spec §6.4 do not include `E_STOPPED`).
8. REST endpoints (spec §8.2):
   - `POST /api/safety/e-stop` body `{reason?: string}`.
   - `POST /api/safety/reset` — clears `E_STOPPED` on all devices + clears all rule latches.
   - `GET /api/safety/rules` — returns loaded rules + per-rule latch status.
   - `POST /api/safety/rules/reload` — re-reads `safety.yaml`.
   - `POST /api/safety/sensors/readings` body `SensorReadingRequest`.
   - `POST /api/safety/active-target` body `ActiveTargetRequest`.
9. `@Scheduled` altitude evaluator that re-runs `altitude_below` rules every `nocs.safety.altitude-eval-interval-ms`.
10. Sensor-offline detection: every reading carries `sensor` + `ts`; SafetyService tracks last-seen per sensor; `sensor_offline` triggers when `now - lastSeen > thresholdSeconds`.
11. Session-history wiring: every E-stop and rule trigger goes through `SessionService.logEvent` so the existing `session_events` table records caller/payload (spec §6.3).
12. Integration test that boots the full Spring context, posts a "rain" reading, and asserts: simulated mount has `park()` called, simulated camera has `abortExposure()` called, both end in `E_STOPPED`, the bus emits `SEQUENCE/abort_requested` and `SAFETY/rule_triggered`, and `GET /api/safety/rules` shows the rule latched.

### Explicitly out of scope for Plan F

- Sequence engine pause/abort *implementation* — Plan G consumes the events Plan F publishes.
- ImageStore wiring of `e_stopped: true` FITS header — Plan D.
- Horizon-mask-aware altitude rule (uses `HorizonMask.minAltitudeAt(az)`) — v0.1 ships only the flat `altitude_below: <degrees>` form; horizon-mask form is a v0.2 extension hooked at the same `SafetyRuleEngine` seam.
- Web UI for safety banner + e-stop button — Plan H.
- Watchdog / client heartbeats — spec §6.2 explicitly says "no watchdog in v0.1".
- Camera "halt cooling" as a new device method — spec §6.3 says "hold current setpoint, do not warm up automatically", which is the default behaviour (we don't issue any new setpoint). The dispatcher documents this as an intentional no-op.
- Multi-rule-per-condition or general DSL — spec §6.1 says "fixed vocabulary, not a general DSL".

## File Structure

All paths are relative to the repo root (`/home/jorjazo/dev/nocs/nocs`). Every file below has one responsibility; none should exceed ~250 lines.

**New main sources** (`src/main/java/dev/nocs/safety/`):

- `SafetyAction.java` — enum `PAUSE_SEQUENCE, ABORT_AND_PARK, E_STOP` with `wire()` / `fromWire()` for YAML.
- `SafetyCondition.java` — sealed interface with four record permits: `HumidityAbove(double percent)`, `RainDetected()`, `AltitudeBelow(double degrees)`, `SensorOffline(String sensor, long thresholdSeconds)`.
- `SafetyRule.java` — record `(String name, SafetyCondition condition, SafetyAction action)`.
- `SafetyRuleParser.java` — parses YAML to `List<SafetyRule>`; rejects unknown verbs with a clear message.
- `SensorReading.java` — record `(String sensor, java.time.Instant ts, java.util.Map<String, Object> values)`.
- `ActiveTarget.java` — record `(String targetId, double raJ2000Deg, double decJ2000Deg, java.time.Instant since)`.
- `SafetyState.java` — mutable snapshot bag. Holds: latest reading per sensor, latest active target, last-seen `Instant` per sensor, per-rule latch (`ACTIVE` / `INACTIVE`), and the latest computed altitude for the active target. All accessors thread-safe.
- `SafetyRuleEngine.java` — pure: given `SafetyState` + `List<SafetyRule>`, returns a `List<TriggeredRule>` and updates latches.
- `SafetyActionDispatcher.java` — runs the side effects of a `SafetyAction`. Depends on `DeviceRegistry` + `EventBus` + `SessionService`.
- `SafetyService.java` — orchestrator: subscribes to `SENSOR` and `SEQUENCE/target_active`, drives the `@Scheduled` altitude evaluator, exposes `eStop`, `reset`, `reload`, `setActiveTarget`, `postReading`, `rules()` to the controller.
- `DeviceEStoppedException.java` — `RuntimeException` thrown by adapter command methods while `state == E_STOPPED`.
- `TriggeredRule.java` — record `(SafetyRule rule, SafetyCondition resolvedCondition, java.time.Instant at)` returned by the engine.
- `api/SafetyController.java` — six endpoints listed under "In scope #8".
- `api/dto/EStopRequest.java`, `SensorReadingRequest.java`, `ActiveTargetRequest.java`, `RuleView.java`, `SafetyStatusView.java`.

**Modified main sources:**

- `events/Topic.java` — add `SENSOR`.
- `device/Device.java` — add default `emergencyStop()` and `resetEStop()` no-ops.
- `device/Mount.java` — Javadoc only; document the contract.
- `device/Camera.java` — Javadoc only; document the contract.
- `device/adapter/IndiMountAdapter.java` — implement `emergencyStop()` (issue abort + park, transition to `E_STOPPED`) and `resetEStop()` (transition `E_STOPPED → IDLE` and clear guard); guard `slew`/`syncTo`/`park`/`unpark`/`abort` with `assertNotEStopped()`.
- `device/adapter/IndiCameraAdapter.java` — implement `emergencyStop()` (issue abort exposure, transition to `E_STOPPED`) and `resetEStop()`; guard `cool`/`expose`/`abortExposure` with `assertNotEStopped()`.
- `device/MountState.java` and `device/CameraState.java` — already include `E_STOPPED`; no change.
- `config/NocsProperties.java` — add `Safety` subrecord.
- `config/AppBeansConfig.java` — wire `SafetyRuleParser`, `SafetyActionDispatcher`, `SafetyService` beans + a single-thread `ScheduledExecutorService` if Spring `@Scheduled` is unavailable in tests (we'll use `@Scheduled` plus `@EnableScheduling`).
- `bootstrap/DataDirBootstrap.java` — copy `safety.example.yaml` into `data_dir/safety.yaml` on first run (mirrors `config.yaml`).
- `NocsApplication.java` — add `@EnableScheduling`.

**Resources:**

- `src/main/resources/safety.example.yaml` — 3-rule example per spec §6.1.
- `src/main/resources/application.yaml` — append `nocs.safety.*` defaults.
- `src/main/resources/config.example.yaml` — append a commented `safety:` section pointing at `safety.yaml`.

**New test sources** (`src/test/java/dev/nocs/safety/`):

- `SensorTopicTest.java` — mirrors the existing `events/TargetTopicTest.java`.
- `SafetyConfigTest.java` — binds `nocs.safety.*` from `@TestPropertySource`.
- `SafetyActionTest.java` — `wire()` / `fromWire()`.
- `SafetyConditionTest.java` — sealed interface ergonomics.
- `SafetyRuleParserTest.java` — happy path + each unknown-verb rejection.
- `SafetyExampleYamlBootstrapTest.java` — `DataDirBootstrap.ensureLayout()` copies `safety.example.yaml`.
- `SafetyStateTest.java` — readings/last-seen/active-target/latch transitions.
- `SafetyRuleEngineTest.java` — one test per condition + idempotency latch + clear-and-retrigger + unknown-sensor.
- `DeviceEStopGuardTest.java` — `IndiMountAdapter` and `IndiCameraAdapter` reject commands after `emergencyStop()`, accept after `resetEStop()`.
- `SafetyActionDispatcherTest.java` — fake `DeviceRegistry` (in-memory `Mount` and `Camera` doubles) + spy `EventBus` + recording `SessionService` double; covers each of the three actions.
- `SafetyServiceTest.java` — full service against real `EventBus`, fake dispatcher; reload from disk; sensor reading triggers the right rule; altitude scheduler ticks.
- `api/SafetyControllerTest.java` — MockMvc happy paths + 401 without bearer.
- `IntegrationSafetyApiTest.java` — full Spring context, posts a rain reading, asserts dispatcher side effects (mount.park called, camera.abortExposure called, both `E_STOPPED`) + bus events + `GET /api/safety/rules` shows latched.

**New test resources:**

- `src/test/resources/safety/rules-valid.yaml` — minimal three-rule fixture.
- `src/test/resources/safety/rules-invalid.yaml` — uses unknown action verb.

## Tasks

Each task is self-contained: files listed, TDD steps with complete code, exact commands with expected output, and a commit at the end. Tasks 1–3 wire the bus topic, config, and base enum; 4–5 build the rule data model + YAML parser; 6 wires bootstrap; 7–8 build the engine + state; 9 adds device-level E-stop; 10 implements the dispatcher; 11 wires the orchestrator + scheduler; 12 ships the REST surface; 13 is the end-to-end integration test; 14 updates docs + the decomposition status table.

---

### Task 1: Add `SENSOR` topic

**Files:**
- Modify: `src/main/java/dev/nocs/events/Topic.java`
- Create: `src/test/java/dev/nocs/safety/SensorTopicTest.java`

- [ ] **Step 1.1: Write the failing test**

Create `src/test/java/dev/nocs/safety/SensorTopicTest.java`:

```java
package dev.nocs.safety;

import dev.nocs.events.Topic;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SensorTopicTest {

    @Test
    void sensorTopicExists() {
        assertThat(Topic.valueOf("SENSOR")).isEqualTo(Topic.SENSOR);
        assertThat(Topic.SENSOR.wire()).isEqualTo("sensor");
        assertThat(Topic.fromWire("sensor")).isEqualTo(Topic.SENSOR);
    }
}
```

- [ ] **Step 1.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.safety.SensorTopicTest'`
Expected: compile failure — `Topic.SENSOR` does not exist.

- [ ] **Step 1.3: Add the enum value**

Modify `src/main/java/dev/nocs/events/Topic.java` to:

```java
package dev.nocs.events;

public enum Topic {
    MOUNT, CAMERA, FILTERWHEEL, FOCUSER,
    SEQUENCE, SAFETY, SESSION, DEVICE_CONNECTION, SYSTEM,
    TARGET, SENSOR;

    public String wire() {
        return name().toLowerCase();
    }

    public static Topic fromWire(String wire) {
        return Topic.valueOf(wire.trim().toUpperCase());
    }
}
```

- [ ] **Step 1.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.safety.SensorTopicTest'`
Expected: `BUILD SUCCESSFUL` with one test passing.

- [ ] **Step 1.5: Commit**

```bash
git add src/main/java/dev/nocs/events/Topic.java \
        src/test/java/dev/nocs/safety/SensorTopicTest.java
git commit -m "feat(events): add SENSOR topic for safety inputs"
```

---

### Task 2: `nocs.safety.*` config

**Files:**
- Modify: `src/main/java/dev/nocs/config/NocsProperties.java`
- Modify: `src/main/resources/application.yaml`
- Modify: `src/main/resources/config.example.yaml`
- Create: `src/test/java/dev/nocs/safety/SafetyConfigTest.java`

- [ ] **Step 2.1: Write the failing binding test**

Create `src/test/java/dev/nocs/safety/SafetyConfigTest.java`:

```java
package dev.nocs.safety;

import dev.nocs.config.NocsProperties;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@TestPropertySource(properties = {
        "nocs.auth.token=t",
        "nocs.safety.rules-path=/tmp/nocs-safety-test.yaml",
        "nocs.safety.altitude-eval-interval-ms=2500",
        "nocs.safety.sensor-offline-default-seconds=42"
})
class SafetyConfigTest {

    @Autowired
    NocsProperties props;

    @Test
    void bindsSafetySection() {
        assertThat(props.safety()).isNotNull();
        assertThat(props.safety().rulesPath()).isEqualTo("/tmp/nocs-safety-test.yaml");
        assertThat(props.safety().altitudeEvalIntervalMs()).isEqualTo(2500L);
        assertThat(props.safety().sensorOfflineDefaultSeconds()).isEqualTo(42L);
    }

    @Test
    void defaultsAreApplied() {
        NocsProperties.Safety s = new NocsProperties.Safety(null, null, null);
        assertThat(s.rulesPath()).isNull();
        assertThat(s.altitudeEvalIntervalMs()).isEqualTo(10_000L);
        assertThat(s.sensorOfflineDefaultSeconds()).isEqualTo(60L);
    }
}
```

- [ ] **Step 2.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.safety.SafetyConfigTest'`
Expected: compile failure — `NocsProperties.safety()` and `NocsProperties.Safety` do not exist.

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
        Targets targets,
        Safety safety) {

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
}
```

- [ ] **Step 2.4: Update `application.yaml` defaults**

Append under the existing `nocs:` block in `src/main/resources/application.yaml`:

```yaml
  safety:
    rules-path: ""
    altitude-eval-interval-ms: 10000
    sensor-offline-default-seconds: 60
```

- [ ] **Step 2.5: Update `config.example.yaml`**

Append to `src/main/resources/config.example.yaml` (before the trailing comment):

```yaml

  # Safety rules (Plan F). On first run, a copy of safety.example.yaml is placed
  # in your data_dir as safety.yaml. Edit it (or point rules-path at another file)
  # to change which conditions trigger pause/abort/e-stop. Reload at runtime via
  # POST /api/safety/rules/reload.
  safety:
    # Empty = use ${data_dir}/safety.yaml. Absolute paths are honoured.
    rules-path: ""
    altitude-eval-interval-ms: 10000
    sensor-offline-default-seconds: 60
```

- [ ] **Step 2.6: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.safety.SafetyConfigTest'`
Expected: both tests pass.

Run: `./gradlew test`
Expected: `BUILD SUCCESSFUL` (no regressions).

- [ ] **Step 2.7: Commit**

```bash
git add src/main/java/dev/nocs/config/NocsProperties.java \
        src/main/resources/application.yaml \
        src/main/resources/config.example.yaml \
        src/test/java/dev/nocs/safety/SafetyConfigTest.java
git commit -m "feat(config): nocs.safety.* binding (rules-path, altitude eval, sensor-offline)"
```

---

### Task 3: `SafetyAction` enum

**Files:**
- Create: `src/main/java/dev/nocs/safety/SafetyAction.java`
- Create: `src/test/java/dev/nocs/safety/SafetyActionTest.java`

- [ ] **Step 3.1: Write the failing test**

Create `src/test/java/dev/nocs/safety/SafetyActionTest.java`:

```java
package dev.nocs.safety;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class SafetyActionTest {

    @Test
    void wireMatchesYamlVocabulary() {
        assertThat(SafetyAction.PAUSE_SEQUENCE.wire()).isEqualTo("pause_sequence");
        assertThat(SafetyAction.ABORT_AND_PARK.wire()).isEqualTo("abort_and_park");
        assertThat(SafetyAction.E_STOP.wire()).isEqualTo("e_stop");
    }

    @Test
    void fromWireRoundTrips() {
        assertThat(SafetyAction.fromWire("pause_sequence")).isEqualTo(SafetyAction.PAUSE_SEQUENCE);
        assertThat(SafetyAction.fromWire("abort_and_park")).isEqualTo(SafetyAction.ABORT_AND_PARK);
        assertThat(SafetyAction.fromWire("e_stop")).isEqualTo(SafetyAction.E_STOP);
    }

    @Test
    void fromWireRejectsUnknown() {
        assertThatThrownBy(() -> SafetyAction.fromWire("nuke_everything"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("nuke_everything");
    }
}
```

- [ ] **Step 3.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.safety.SafetyActionTest'`
Expected: compile failure — `SafetyAction` does not exist.

- [ ] **Step 3.3: Implement the enum**

Create `src/main/java/dev/nocs/safety/SafetyAction.java`:

```java
package dev.nocs.safety;

public enum SafetyAction {
    PAUSE_SEQUENCE,
    ABORT_AND_PARK,
    E_STOP;

    public String wire() {
        return name().toLowerCase();
    }

    public static SafetyAction fromWire(String wire) {
        if (wire == null) {
            throw new IllegalArgumentException("safety action is required");
        }
        try {
            return SafetyAction.valueOf(wire.trim().toUpperCase());
        } catch (IllegalArgumentException e) {
            throw new IllegalArgumentException("unknown safety action: " + wire, e);
        }
    }
}
```

- [ ] **Step 3.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.safety.SafetyActionTest'`
Expected: three tests pass.

- [ ] **Step 3.5: Commit**

```bash
git add src/main/java/dev/nocs/safety/SafetyAction.java \
        src/test/java/dev/nocs/safety/SafetyActionTest.java
git commit -m "feat(safety): SafetyAction enum (pause/abort/e-stop)"
```

---

### Task 4: `SafetyCondition` sealed interface

**Files:**
- Create: `src/main/java/dev/nocs/safety/SafetyCondition.java`
- Create: `src/test/java/dev/nocs/safety/SafetyConditionTest.java`

- [ ] **Step 4.1: Write the failing test**

Create `src/test/java/dev/nocs/safety/SafetyConditionTest.java`:

```java
package dev.nocs.safety;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SafetyConditionTest {

    @Test
    void recordsCarryTheirParameters() {
        assertThat(new SafetyCondition.HumidityAbove(85).percent()).isEqualTo(85.0);
        assertThat(new SafetyCondition.RainDetected()).isInstanceOf(SafetyCondition.class);
        assertThat(new SafetyCondition.AltitudeBelow(20).degrees()).isEqualTo(20.0);
        assertThat(new SafetyCondition.SensorOffline("weather", 120).sensor()).isEqualTo("weather");
        assertThat(new SafetyCondition.SensorOffline("weather", 120).thresholdSeconds()).isEqualTo(120L);
    }

    @Test
    void wireNamesAreStable() {
        assertThat(SafetyCondition.wireOf(new SafetyCondition.HumidityAbove(85))).isEqualTo("humidity_above");
        assertThat(SafetyCondition.wireOf(new SafetyCondition.RainDetected())).isEqualTo("rain_detected");
        assertThat(SafetyCondition.wireOf(new SafetyCondition.AltitudeBelow(20))).isEqualTo("altitude_below");
        assertThat(SafetyCondition.wireOf(new SafetyCondition.SensorOffline("weather", 1))).isEqualTo("sensor_offline");
    }
}
```

- [ ] **Step 4.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.safety.SafetyConditionTest'`
Expected: compile failure — `SafetyCondition` does not exist.

- [ ] **Step 4.3: Implement the sealed interface**

Create `src/main/java/dev/nocs/safety/SafetyCondition.java`:

```java
package dev.nocs.safety;

public sealed interface SafetyCondition
        permits SafetyCondition.HumidityAbove,
                SafetyCondition.RainDetected,
                SafetyCondition.AltitudeBelow,
                SafetyCondition.SensorOffline {

    record HumidityAbove(double percent) implements SafetyCondition {}

    record RainDetected() implements SafetyCondition {}

    record AltitudeBelow(double degrees) implements SafetyCondition {}

    record SensorOffline(String sensor, long thresholdSeconds) implements SafetyCondition {
        public SensorOffline {
            if (sensor == null || sensor.isBlank()) {
                throw new IllegalArgumentException("sensor name is required for sensor_offline");
            }
            if (thresholdSeconds <= 0) {
                throw new IllegalArgumentException("thresholdSeconds must be positive");
            }
        }
    }

    static String wireOf(SafetyCondition c) {
        return switch (c) {
            case HumidityAbove ignored -> "humidity_above";
            case RainDetected ignored -> "rain_detected";
            case AltitudeBelow ignored -> "altitude_below";
            case SensorOffline ignored -> "sensor_offline";
        };
    }
}
```

- [ ] **Step 4.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.safety.SafetyConditionTest'`
Expected: two tests pass.

- [ ] **Step 4.5: Commit**

```bash
git add src/main/java/dev/nocs/safety/SafetyCondition.java \
        src/test/java/dev/nocs/safety/SafetyConditionTest.java
git commit -m "feat(safety): SafetyCondition sealed interface (humidity/rain/altitude/offline)"
```

---

### Task 5: `SafetyRule` + YAML parser

**Files:**
- Create: `src/main/java/dev/nocs/safety/SafetyRule.java`
- Create: `src/main/java/dev/nocs/safety/SafetyRuleParser.java`
- Create: `src/test/resources/safety/rules-valid.yaml`
- Create: `src/test/resources/safety/rules-invalid.yaml`
- Create: `src/test/java/dev/nocs/safety/SafetyRuleParserTest.java`

- [ ] **Step 5.1: Create the valid fixture**

Create `src/test/resources/safety/rules-valid.yaml`:

```yaml
rules:
  - name: humidity-high
    when: { humidity_above: 90 }
    then: pause_sequence
  - name: rain
    when: { rain_detected: true }
    then: e_stop
  - name: low-altitude
    when: { altitude_below: 20 }
    then: abort_and_park
  - name: weather-offline
    when: { sensor_offline: { sensor: weather, threshold_seconds: 120 } }
    then: pause_sequence
```

- [ ] **Step 5.2: Create the invalid fixture**

Create `src/test/resources/safety/rules-invalid.yaml`:

```yaml
rules:
  - name: bad
    when: { humidity_above: 90 }
    then: nuke_everything
```

- [ ] **Step 5.3: Write the failing test**

Create `src/test/java/dev/nocs/safety/SafetyRuleParserTest.java`:

```java
package dev.nocs.safety;

import java.io.InputStream;
import java.util.List;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class SafetyRuleParserTest {

    @Test
    void parsesAllFourConditions() throws Exception {
        List<SafetyRule> rules;
        try (InputStream in = openFixture("rules-valid.yaml")) {
            rules = new SafetyRuleParser().parse(in);
        }

        assertThat(rules).hasSize(4);

        SafetyRule humidity = rules.get(0);
        assertThat(humidity.name()).isEqualTo("humidity-high");
        assertThat(humidity.condition()).isEqualTo(new SafetyCondition.HumidityAbove(90));
        assertThat(humidity.action()).isEqualTo(SafetyAction.PAUSE_SEQUENCE);

        assertThat(rules.get(1).condition()).isEqualTo(new SafetyCondition.RainDetected());
        assertThat(rules.get(1).action()).isEqualTo(SafetyAction.E_STOP);

        assertThat(rules.get(2).condition()).isEqualTo(new SafetyCondition.AltitudeBelow(20));
        assertThat(rules.get(2).action()).isEqualTo(SafetyAction.ABORT_AND_PARK);

        assertThat(rules.get(3).condition()).isEqualTo(new SafetyCondition.SensorOffline("weather", 120));
    }

    @Test
    void rejectsUnknownAction() throws Exception {
        try (InputStream in = openFixture("rules-invalid.yaml")) {
            assertThatThrownBy(() -> new SafetyRuleParser().parse(in))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("nuke_everything");
        }
    }

    @Test
    void emptyFileYieldsEmptyList() throws Exception {
        List<SafetyRule> rules = new SafetyRuleParser().parseString("");
        assertThat(rules).isEmpty();
    }

    @Test
    void rulesKeyMustExistOrReturnEmpty() throws Exception {
        List<SafetyRule> rules = new SafetyRuleParser().parseString("# comment only\n");
        assertThat(rules).isEmpty();
    }

    @Test
    void rejectsRuleMissingCondition() {
        String yaml = "rules:\n  - name: x\n    then: e_stop\n";
        assertThatThrownBy(() -> new SafetyRuleParser().parseString(yaml))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("when");
    }

    @Test
    void rejectsRuleMissingAction() {
        String yaml = "rules:\n  - name: x\n    when: { rain_detected: true }\n";
        assertThatThrownBy(() -> new SafetyRuleParser().parseString(yaml))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("then");
    }

    private InputStream openFixture(String name) {
        InputStream in = getClass().getClassLoader().getResourceAsStream("safety/" + name);
        if (in == null) {
            throw new IllegalStateException("fixture not on classpath: safety/" + name);
        }
        return in;
    }
}
```

- [ ] **Step 5.4: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.safety.SafetyRuleParserTest'`
Expected: compile failure — `SafetyRule` and `SafetyRuleParser` do not exist.

- [ ] **Step 5.5: Implement `SafetyRule`**

Create `src/main/java/dev/nocs/safety/SafetyRule.java`:

```java
package dev.nocs.safety;

public record SafetyRule(String name, SafetyCondition condition, SafetyAction action) {

    public SafetyRule {
        if (name == null || name.isBlank()) {
            throw new IllegalArgumentException("rule name is required");
        }
        if (condition == null) {
            throw new IllegalArgumentException("rule condition is required");
        }
        if (action == null) {
            throw new IllegalArgumentException("rule action is required");
        }
    }
}
```

- [ ] **Step 5.6: Implement `SafetyRuleParser`**

Create `src/main/java/dev/nocs/safety/SafetyRuleParser.java`:

```java
package dev.nocs.safety;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

public final class SafetyRuleParser {

    private static final ObjectMapper YAML = new ObjectMapper(new YAMLFactory());

    public List<SafetyRule> parse(InputStream in) {
        try {
            byte[] bytes = in.readAllBytes();
            return parseString(new String(bytes, StandardCharsets.UTF_8));
        } catch (IOException e) {
            throw new IllegalArgumentException("failed to read safety rules: " + e.getMessage(), e);
        }
    }

    public List<SafetyRule> parseString(String yaml) {
        if (yaml == null || yaml.isBlank()) {
            return List.of();
        }
        Map<String, Object> root;
        try {
            root = YAML.readValue(yaml, Map.class);
        } catch (IOException e) {
            throw new IllegalArgumentException("invalid safety YAML: " + e.getMessage(), e);
        }
        if (root == null) {
            return List.of();
        }
        Object rulesNode = root.get("rules");
        if (rulesNode == null) {
            return List.of();
        }
        if (!(rulesNode instanceof List<?> rawRules)) {
            throw new IllegalArgumentException("'rules' must be a list");
        }
        List<SafetyRule> out = new ArrayList<>(rawRules.size());
        for (int i = 0; i < rawRules.size(); i++) {
            Object raw = rawRules.get(i);
            if (!(raw instanceof Map<?, ?> map)) {
                throw new IllegalArgumentException("rule[" + i + "] must be a map");
            }
            out.add(toRule(i, map));
        }
        return List.copyOf(out);
    }

    private SafetyRule toRule(int idx, Map<?, ?> raw) {
        Object name = raw.get("name");
        if (!(name instanceof String s) || s.isBlank()) {
            throw new IllegalArgumentException("rule[" + idx + "].name is required");
        }
        Object whenNode = raw.get("when");
        if (whenNode == null) {
            throw new IllegalArgumentException("rule[" + idx + "].when is required");
        }
        Object thenNode = raw.get("then");
        if (thenNode == null) {
            throw new IllegalArgumentException("rule[" + idx + "].then is required");
        }
        SafetyCondition condition = toCondition(idx, whenNode);
        SafetyAction action = SafetyAction.fromWire(thenNode.toString());
        return new SafetyRule(s, condition, action);
    }

    private SafetyCondition toCondition(int idx, Object node) {
        if (!(node instanceof Map<?, ?> map) || map.size() != 1) {
            throw new IllegalArgumentException(
                    "rule[" + idx + "].when must be a single-key map (humidity_above|rain_detected|altitude_below|sensor_offline)");
        }
        Map.Entry<?, ?> e = map.entrySet().iterator().next();
        String key = String.valueOf(e.getKey());
        Object val = e.getValue();
        return switch (key) {
            case "humidity_above" -> new SafetyCondition.HumidityAbove(asDouble(idx, key, val));
            case "rain_detected" -> {
                if (!Boolean.TRUE.equals(val)) {
                    throw new IllegalArgumentException("rule[" + idx + "].when.rain_detected must be true");
                }
                yield new SafetyCondition.RainDetected();
            }
            case "altitude_below" -> new SafetyCondition.AltitudeBelow(asDouble(idx, key, val));
            case "sensor_offline" -> {
                if (!(val instanceof Map<?, ?> sub)) {
                    throw new IllegalArgumentException(
                            "rule[" + idx + "].when.sensor_offline must be {sensor, threshold_seconds}");
                }
                Object sensor = sub.get("sensor");
                Object threshold = sub.get("threshold_seconds");
                if (!(sensor instanceof String ss) || ss.isBlank()) {
                    throw new IllegalArgumentException(
                            "rule[" + idx + "].when.sensor_offline.sensor is required");
                }
                yield new SafetyCondition.SensorOffline(ss, asLong(idx, "threshold_seconds", threshold));
            }
            default -> throw new IllegalArgumentException(
                    "rule[" + idx + "].when has unknown condition: " + key);
        };
    }

    private double asDouble(int idx, String key, Object val) {
        if (val instanceof Number n) {
            return n.doubleValue();
        }
        throw new IllegalArgumentException("rule[" + idx + "]." + key + " must be a number, got: " + val);
    }

    private long asLong(int idx, String key, Object val) {
        if (val instanceof Number n) {
            return n.longValue();
        }
        throw new IllegalArgumentException("rule[" + idx + "]." + key + " must be a number, got: " + val);
    }
}
```

- [ ] **Step 5.7: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.safety.SafetyRuleParserTest'`
Expected: six tests pass.

- [ ] **Step 5.8: Commit**

```bash
git add src/main/java/dev/nocs/safety/SafetyRule.java \
        src/main/java/dev/nocs/safety/SafetyRuleParser.java \
        src/test/resources/safety/rules-valid.yaml \
        src/test/resources/safety/rules-invalid.yaml \
        src/test/java/dev/nocs/safety/SafetyRuleParserTest.java
git commit -m "feat(safety): SafetyRule + YAML parser for fixed v0.1 vocabulary"
```

---

### Task 6: `safety.example.yaml` + `DataDirBootstrap` copy

**Files:**
- Create: `src/main/resources/safety.example.yaml`
- Modify: `src/main/java/dev/nocs/bootstrap/DataDirBootstrap.java`
- Create: `src/test/java/dev/nocs/safety/SafetyExampleYamlBootstrapTest.java`

- [ ] **Step 6.1: Create the example yaml**

Create `src/main/resources/safety.example.yaml`:

```yaml
# NOCS safety rules. v0.1 supports a fixed vocabulary; see docs/superpowers/specs.
# Reload at runtime via POST /api/safety/rules/reload.
rules:
  - name: humidity-high
    when: { humidity_above: 90 }
    then: pause_sequence

  - name: rain
    when: { rain_detected: true }
    then: e_stop

  - name: low-altitude
    when: { altitude_below: 20 }
    then: abort_and_park

  - name: weather-offline
    when: { sensor_offline: { sensor: weather, threshold_seconds: 120 } }
    then: pause_sequence
```

- [ ] **Step 6.2: Write the failing bootstrap test**

Create `src/test/java/dev/nocs/safety/SafetyExampleYamlBootstrapTest.java`:

```java
package dev.nocs.safety;

import dev.nocs.bootstrap.DataDirBootstrap;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.assertj.core.api.Assertions.assertThat;

class SafetyExampleYamlBootstrapTest {

    @Test
    void firstRunCopiesSafetyExample(@TempDir Path tmp) throws IOException {
        DataDirBootstrap.ensureLayout(tmp);

        Path safetyYaml = tmp.resolve("safety.yaml");
        assertThat(Files.exists(safetyYaml)).isTrue();
        String contents = Files.readString(safetyYaml);
        assertThat(contents).contains("rain_detected");
        assertThat(contents).contains("e_stop");
    }

    @Test
    void secondRunDoesNotOverwriteUserEdits(@TempDir Path tmp) throws IOException {
        DataDirBootstrap.ensureLayout(tmp);
        Path safetyYaml = tmp.resolve("safety.yaml");
        Files.writeString(safetyYaml, "rules: []\n");

        DataDirBootstrap.ensureLayout(tmp);

        assertThat(Files.readString(safetyYaml)).isEqualTo("rules: []\n");
    }
}
```

- [ ] **Step 6.3: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.safety.SafetyExampleYamlBootstrapTest'`
Expected: first test fails — `safety.yaml` is not created by `ensureLayout`.

- [ ] **Step 6.4: Extend `DataDirBootstrap`**

Replace `src/main/java/dev/nocs/bootstrap/DataDirBootstrap.java`:

```java
package dev.nocs.bootstrap;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;

public final class DataDirBootstrap {

    private DataDirBootstrap() {}

    public static Path resolveDataDir() {
        String override = System.getenv("NOCS_DATA_DIR");
        if (override != null && !override.isBlank()) {
            return Paths.get(override).toAbsolutePath();
        }
        String os = System.getProperty("os.name", "").toLowerCase();
        if (os.contains("win")) {
            String appData = System.getenv("APPDATA");
            return Paths.get(appData == null ? System.getProperty("user.home") : appData, "nocs").toAbsolutePath();
        }
        String xdg = System.getenv("XDG_DATA_HOME");
        if (xdg != null && !xdg.isBlank()) {
            return Paths.get(xdg, "nocs").toAbsolutePath();
        }
        return Paths.get(System.getProperty("user.home"), ".local", "share", "nocs").toAbsolutePath();
    }

    public static Path ensureLayout(Path dataDir) throws IOException {
        Files.createDirectories(dataDir);
        Files.createDirectories(dataDir.resolve("sessions"));
        Files.createDirectories(dataDir.resolve("logs"));
        Path configFile = copyIfMissing(dataDir, "config.example.yaml", "config.yaml");
        copyIfMissing(dataDir, "safety.example.yaml", "safety.yaml");
        return configFile;
    }

    private static Path copyIfMissing(Path dataDir, String resource, String target) throws IOException {
        Path dest = dataDir.resolve(target);
        if (Files.exists(dest)) {
            return dest;
        }
        try (InputStream in = DataDirBootstrap.class.getResourceAsStream("/" + resource)) {
            if (in == null) {
                throw new IOException(resource + " missing from classpath");
            }
            Files.copy(in, dest, StandardCopyOption.REPLACE_EXISTING);
        }
        return dest;
    }
}
```

- [ ] **Step 6.5: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.safety.SafetyExampleYamlBootstrapTest'`
Expected: both tests pass.

Run the full suite to confirm the existing `TokenBootstrapTest` is still happy:
Run: `./gradlew test`
Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 6.6: Commit**

```bash
git add src/main/resources/safety.example.yaml \
        src/main/java/dev/nocs/bootstrap/DataDirBootstrap.java \
        src/test/java/dev/nocs/safety/SafetyExampleYamlBootstrapTest.java
git commit -m "feat(bootstrap): copy safety.example.yaml on first run"
```

---

### Task 7: `SensorReading`, `ActiveTarget`, `SafetyState`

**Files:**
- Create: `src/main/java/dev/nocs/safety/SensorReading.java`
- Create: `src/main/java/dev/nocs/safety/ActiveTarget.java`
- Create: `src/main/java/dev/nocs/safety/SafetyState.java`
- Create: `src/test/java/dev/nocs/safety/SafetyStateTest.java`

- [ ] **Step 7.1: Write the failing test**

Create `src/test/java/dev/nocs/safety/SafetyStateTest.java`:

```java
package dev.nocs.safety;

import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SafetyStateTest {

    @Test
    void recordsMostRecentReadingPerSensor() {
        SafetyState state = new SafetyState();

        state.recordReading(new SensorReading("weather", Instant.parse("2026-04-22T10:00:00Z"),
                Map.of("humidity", 80.0, "rain_detected", false)));
        state.recordReading(new SensorReading("weather", Instant.parse("2026-04-22T10:01:00Z"),
                Map.of("humidity", 92.0, "rain_detected", true)));

        assertThat(state.lastReading("weather")).isPresent();
        assertThat(state.lastReading("weather").get().values().get("humidity")).isEqualTo(92.0);
        assertThat(state.lastSeen("weather")).hasValue(Instant.parse("2026-04-22T10:01:00Z"));
        assertThat(state.lastReading("missing")).isEmpty();
    }

    @Test
    void tracksActiveTarget() {
        SafetyState state = new SafetyState();
        ActiveTarget t = new ActiveTarget("messier:M31", 10.685, 41.269, Instant.now());

        assertThat(state.activeTarget()).isEmpty();
        state.setActiveTarget(t);
        assertThat(state.activeTarget()).hasValue(t);
        state.setActiveTarget(null);
        assertThat(state.activeTarget()).isEmpty();
    }

    @Test
    void tracksLatchPerRule() {
        SafetyState state = new SafetyState();

        assertThat(state.isLatched("rain")).isFalse();
        state.latch("rain");
        assertThat(state.isLatched("rain")).isTrue();
        state.unlatch("rain");
        assertThat(state.isLatched("rain")).isFalse();

        state.latch("a");
        state.latch("b");
        state.unlatchAll();
        assertThat(state.isLatched("a")).isFalse();
        assertThat(state.isLatched("b")).isFalse();
    }

    @Test
    void cachesLatestAltitudeForActiveTarget() {
        SafetyState state = new SafetyState();
        assertThat(state.lastAltitudeDeg()).isEmpty();
        state.setLastAltitudeDeg(15.5);
        assertThat(state.lastAltitudeDeg()).hasValue(15.5);
    }
}
```

- [ ] **Step 7.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.safety.SafetyStateTest'`
Expected: compile failure — types do not exist.

- [ ] **Step 7.3: Implement `SensorReading`**

Create `src/main/java/dev/nocs/safety/SensorReading.java`:

```java
package dev.nocs.safety;

import java.time.Instant;
import java.util.Map;

public record SensorReading(String sensor, Instant ts, Map<String, Object> values) {

    public SensorReading {
        if (sensor == null || sensor.isBlank()) {
            throw new IllegalArgumentException("sensor name is required");
        }
        if (ts == null) {
            ts = Instant.now();
        }
        values = values == null ? Map.of() : Map.copyOf(values);
    }

    public boolean booleanValue(String key) {
        Object v = values.get(key);
        return v instanceof Boolean b && b;
    }

    public Double doubleValue(String key) {
        Object v = values.get(key);
        if (v instanceof Number n) {
            return n.doubleValue();
        }
        return null;
    }
}
```

- [ ] **Step 7.4: Implement `ActiveTarget`**

Create `src/main/java/dev/nocs/safety/ActiveTarget.java`:

```java
package dev.nocs.safety;

import java.time.Instant;

public record ActiveTarget(String targetId, double raJ2000Deg, double decJ2000Deg, Instant since) {

    public ActiveTarget {
        if (targetId == null || targetId.isBlank()) {
            throw new IllegalArgumentException("targetId is required");
        }
        if (Double.isNaN(raJ2000Deg) || Double.isNaN(decJ2000Deg)) {
            throw new IllegalArgumentException("ra/dec must be numeric");
        }
        if (since == null) {
            since = Instant.now();
        }
    }
}
```

- [ ] **Step 7.5: Implement `SafetyState`**

Create `src/main/java/dev/nocs/safety/SafetyState.java`:

```java
package dev.nocs.safety;

import java.time.Instant;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicReference;

public final class SafetyState {

    private final Map<String, SensorReading> readings = new ConcurrentHashMap<>();
    private final Set<String> latchedRules = ConcurrentHashMap.newKeySet();
    private final AtomicReference<ActiveTarget> activeTarget = new AtomicReference<>();
    private final AtomicReference<Double> lastAltitudeDeg = new AtomicReference<>();

    public void recordReading(SensorReading reading) {
        readings.put(reading.sensor(), reading);
    }

    public Optional<SensorReading> lastReading(String sensor) {
        return Optional.ofNullable(readings.get(sensor));
    }

    public Optional<Instant> lastSeen(String sensor) {
        return lastReading(sensor).map(SensorReading::ts);
    }

    public Map<String, SensorReading> readings() {
        return Map.copyOf(readings);
    }

    public void setActiveTarget(ActiveTarget t) {
        activeTarget.set(t);
        if (t == null) {
            lastAltitudeDeg.set(null);
        }
    }

    public Optional<ActiveTarget> activeTarget() {
        return Optional.ofNullable(activeTarget.get());
    }

    public void setLastAltitudeDeg(Double altDeg) {
        lastAltitudeDeg.set(altDeg);
    }

    public Optional<Double> lastAltitudeDeg() {
        return Optional.ofNullable(lastAltitudeDeg.get());
    }

    public boolean isLatched(String ruleName) {
        return latchedRules.contains(ruleName);
    }

    public void latch(String ruleName) {
        latchedRules.add(ruleName);
    }

    public void unlatch(String ruleName) {
        latchedRules.remove(ruleName);
    }

    public void unlatchAll() {
        latchedRules.clear();
    }

    public Set<String> latchedRules() {
        return Set.copyOf(latchedRules);
    }
}
```

- [ ] **Step 7.6: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.safety.SafetyStateTest'`
Expected: four tests pass.

- [ ] **Step 7.7: Commit**

```bash
git add src/main/java/dev/nocs/safety/SensorReading.java \
        src/main/java/dev/nocs/safety/ActiveTarget.java \
        src/main/java/dev/nocs/safety/SafetyState.java \
        src/test/java/dev/nocs/safety/SafetyStateTest.java
git commit -m "feat(safety): SensorReading, ActiveTarget, SafetyState snapshot bag"
```

---

### Task 8: `SafetyRuleEngine` (pure evaluator + idempotent latch)

**Files:**
- Create: `src/main/java/dev/nocs/safety/TriggeredRule.java`
- Create: `src/main/java/dev/nocs/safety/SafetyRuleEngine.java`
- Create: `src/test/java/dev/nocs/safety/SafetyRuleEngineTest.java`

- [ ] **Step 8.1: Write the failing test**

Create `src/test/java/dev/nocs/safety/SafetyRuleEngineTest.java`:

```java
package dev.nocs.safety;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SafetyRuleEngineTest {

    private final Instant now = Instant.parse("2026-04-22T10:00:00Z");
    private final Clock clock = Clock.fixed(now, ZoneOffset.UTC);
    private final SafetyRuleEngine engine = new SafetyRuleEngine(clock);

    @Test
    void humidityAboveTriggersWhenReadingExceedsThreshold() {
        SafetyState state = new SafetyState();
        state.recordReading(new SensorReading("weather", now, Map.of("humidity", 95.0)));

        SafetyRule rule = rule("hum", new SafetyCondition.HumidityAbove(90), SafetyAction.PAUSE_SEQUENCE);
        List<TriggeredRule> fired = engine.evaluate(state, List.of(rule));

        assertThat(fired).hasSize(1);
        assertThat(fired.get(0).rule()).isEqualTo(rule);
        assertThat(state.isLatched("hum")).isTrue();
    }

    @Test
    void humidityBelowThresholdDoesNotTrigger() {
        SafetyState state = new SafetyState();
        state.recordReading(new SensorReading("weather", now, Map.of("humidity", 50.0)));

        SafetyRule rule = rule("hum", new SafetyCondition.HumidityAbove(90), SafetyAction.PAUSE_SEQUENCE);
        assertThat(engine.evaluate(state, List.of(rule))).isEmpty();
    }

    @Test
    void rainDetectedTriggersOnTrueOnly() {
        SafetyState state = new SafetyState();
        SafetyRule rule = rule("rain", new SafetyCondition.RainDetected(), SafetyAction.E_STOP);

        state.recordReading(new SensorReading("weather", now, Map.of("rain_detected", false)));
        assertThat(engine.evaluate(state, List.of(rule))).isEmpty();

        state.recordReading(new SensorReading("weather", now.plusSeconds(1), Map.of("rain_detected", true)));
        assertThat(engine.evaluate(state, List.of(rule))).hasSize(1);
    }

    @Test
    void altitudeBelowTriggersOnlyWhenAltitudeKnownAndBelow() {
        SafetyState state = new SafetyState();
        SafetyRule rule = rule("alt", new SafetyCondition.AltitudeBelow(20), SafetyAction.ABORT_AND_PARK);

        assertThat(engine.evaluate(state, List.of(rule))).isEmpty();

        state.setLastAltitudeDeg(25.0);
        assertThat(engine.evaluate(state, List.of(rule))).isEmpty();

        state.setLastAltitudeDeg(15.0);
        assertThat(engine.evaluate(state, List.of(rule))).hasSize(1);
    }

    @Test
    void sensorOfflineTriggersAfterThreshold() {
        SafetyState state = new SafetyState();
        SafetyRule rule = rule("offline",
                new SafetyCondition.SensorOffline("weather", 60),
                SafetyAction.PAUSE_SEQUENCE);

        // No reading at all => offline.
        assertThat(engine.evaluate(state, List.of(rule))).hasSize(1);
        state.unlatchAll();

        // Recent reading => online.
        state.recordReading(new SensorReading("weather", now.minusSeconds(30), Map.of()));
        assertThat(engine.evaluate(state, List.of(rule))).isEmpty();

        // Stale reading => offline.
        state.recordReading(new SensorReading("weather", now.minusSeconds(120), Map.of()));
        assertThat(engine.evaluate(state, List.of(rule))).hasSize(1);
    }

    @Test
    void latchedRuleDoesNotRefireUntilConditionClears() {
        SafetyState state = new SafetyState();
        state.recordReading(new SensorReading("weather", now, Map.of("rain_detected", true)));

        SafetyRule rule = rule("rain", new SafetyCondition.RainDetected(), SafetyAction.E_STOP);

        assertThat(engine.evaluate(state, List.of(rule))).hasSize(1);
        assertThat(engine.evaluate(state, List.of(rule))).isEmpty(); // latched

        state.recordReading(new SensorReading("weather", now.plusSeconds(60), Map.of("rain_detected", false)));
        assertThat(engine.evaluate(state, List.of(rule))).isEmpty(); // clears latch but does not fire
        assertThat(state.isLatched("rain")).isFalse();

        state.recordReading(new SensorReading("weather", now.plusSeconds(120), Map.of("rain_detected", true)));
        assertThat(engine.evaluate(state, List.of(rule))).hasSize(1); // refires after clear
    }

    private SafetyRule rule(String name, SafetyCondition c, SafetyAction a) {
        return new SafetyRule(name, c, a);
    }
}
```

- [ ] **Step 8.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.safety.SafetyRuleEngineTest'`
Expected: compile failure — `TriggeredRule` and `SafetyRuleEngine` do not exist.

- [ ] **Step 8.3: Implement `TriggeredRule`**

Create `src/main/java/dev/nocs/safety/TriggeredRule.java`:

```java
package dev.nocs.safety;

import java.time.Instant;

public record TriggeredRule(SafetyRule rule, SafetyCondition resolvedCondition, Instant at) {

    public TriggeredRule {
        if (rule == null || resolvedCondition == null || at == null) {
            throw new IllegalArgumentException("rule/condition/at all required");
        }
    }
}
```

- [ ] **Step 8.4: Implement `SafetyRuleEngine`**

Create `src/main/java/dev/nocs/safety/SafetyRuleEngine.java`:

```java
package dev.nocs.safety;

import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

public final class SafetyRuleEngine {

    private final Clock clock;

    public SafetyRuleEngine() {
        this(Clock.systemUTC());
    }

    public SafetyRuleEngine(Clock clock) {
        this.clock = clock;
    }

    public List<TriggeredRule> evaluate(SafetyState state, List<SafetyRule> rules) {
        Instant now = clock.instant();
        List<TriggeredRule> fired = new ArrayList<>();
        for (SafetyRule rule : rules) {
            boolean active = isActive(state, rule.condition(), now);
            boolean wasLatched = state.isLatched(rule.name());
            if (active && !wasLatched) {
                state.latch(rule.name());
                fired.add(new TriggeredRule(rule, rule.condition(), now));
            } else if (!active && wasLatched) {
                state.unlatch(rule.name());
            }
        }
        return List.copyOf(fired);
    }

    private boolean isActive(SafetyState state, SafetyCondition c, Instant now) {
        return switch (c) {
            case SafetyCondition.HumidityAbove h -> anyReadingExceeds(state, "humidity", h.percent());
            case SafetyCondition.RainDetected ignored -> anyReadingTrue(state, "rain_detected");
            case SafetyCondition.AltitudeBelow a -> state.lastAltitudeDeg().map(d -> d < a.degrees()).orElse(false);
            case SafetyCondition.SensorOffline o -> isOffline(state, o, now);
        };
    }

    private boolean anyReadingExceeds(SafetyState state, String key, double threshold) {
        for (SensorReading r : state.readings().values()) {
            Double v = r.doubleValue(key);
            if (v != null && v > threshold) {
                return true;
            }
        }
        return false;
    }

    private boolean anyReadingTrue(SafetyState state, String key) {
        for (SensorReading r : state.readings().values()) {
            if (r.booleanValue(key)) {
                return true;
            }
        }
        return false;
    }

    private boolean isOffline(SafetyState state, SafetyCondition.SensorOffline o, Instant now) {
        Optional<Instant> seen = state.lastSeen(o.sensor());
        if (seen.isEmpty()) {
            return true;
        }
        return seen.get().isBefore(now.minusSeconds(o.thresholdSeconds()));
    }
}
```

- [ ] **Step 8.5: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.safety.SafetyRuleEngineTest'`
Expected: six tests pass.

- [ ] **Step 8.6: Commit**

```bash
git add src/main/java/dev/nocs/safety/TriggeredRule.java \
        src/main/java/dev/nocs/safety/SafetyRuleEngine.java \
        src/test/java/dev/nocs/safety/SafetyRuleEngineTest.java
git commit -m "feat(safety): pure rule engine with latched idempotent triggers"
```

---

### Task 9: Device E-stop — interface + adapter overrides + guard

**Files:**
- Create: `src/main/java/dev/nocs/safety/DeviceEStoppedException.java`
- Modify: `src/main/java/dev/nocs/device/Device.java`
- Modify: `src/main/java/dev/nocs/device/adapter/IndiMountAdapter.java`
- Modify: `src/main/java/dev/nocs/device/adapter/IndiCameraAdapter.java`
- Create: `src/test/java/dev/nocs/safety/DeviceEStopGuardTest.java`

- [ ] **Step 9.1: Write the failing test**

Create `src/test/java/dev/nocs/safety/DeviceEStopGuardTest.java`:

```java
package dev.nocs.safety;

import dev.nocs.device.DeviceId;
import dev.nocs.device.MountState;
import dev.nocs.device.CameraState;
import dev.nocs.device.adapter.IndiCameraAdapter;
import dev.nocs.device.adapter.IndiMountAdapter;
import dev.nocs.events.EventBus;
import dev.nocs.indi.IndiClient;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;

class DeviceEStopGuardTest {

    @Test
    void mountRejectsCommandsAfterEmergencyStop() {
        IndiClient client = mock(IndiClient.class);
        EventBus bus = new EventBus();
        IndiMountAdapter mount = new IndiMountAdapter("Sim", new DeviceId("sim"), client, bus);

        mount.emergencyStop();
        assertThat(mount.state()).isEqualTo(MountState.E_STOPPED);

        assertThatThrownBy(() -> mount.slew(0, 0)).isInstanceOf(DeviceEStoppedException.class);
        assertThatThrownBy(() -> mount.park()).isInstanceOf(DeviceEStoppedException.class);
        assertThatThrownBy(() -> mount.unpark()).isInstanceOf(DeviceEStoppedException.class);
        assertThatThrownBy(() -> mount.syncTo(0, 0)).isInstanceOf(DeviceEStoppedException.class);

        mount.resetEStop();
        assertThat(mount.state()).isEqualTo(MountState.IDLE);
    }

    @Test
    void cameraRejectsCommandsAfterEmergencyStop() {
        IndiClient client = mock(IndiClient.class);
        EventBus bus = new EventBus();
        IndiCameraAdapter camera =
                new IndiCameraAdapter("SimCcd", new DeviceId("simccd"), client, bus, (id, b, fmt) -> {});

        camera.emergencyStop();
        assertThat(camera.state()).isEqualTo(CameraState.E_STOPPED);

        assertThatThrownBy(() -> camera.expose(1.0)).isInstanceOf(DeviceEStoppedException.class);
        assertThatThrownBy(() -> camera.cool(-10)).isInstanceOf(DeviceEStoppedException.class);
        assertThatThrownBy(() -> camera.abortExposure()).isInstanceOf(DeviceEStoppedException.class);

        camera.resetEStop();
        assertThat(camera.state()).isEqualTo(CameraState.IDLE);
    }

    @Test
    void resetIsNoopWhenNotEStopped() {
        IndiClient client = mock(IndiClient.class);
        EventBus bus = new EventBus();
        IndiMountAdapter mount = new IndiMountAdapter("Sim", new DeviceId("sim"), client, bus);

        MountState before = mount.state();
        mount.resetEStop();
        assertThat(mount.state()).isEqualTo(before);
    }
}
```

> **Note on `mock(IndiClient.class)`:** `spring-boot-starter-test` already brings in Mockito 5; no new dependency needed.

- [ ] **Step 9.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.safety.DeviceEStopGuardTest'`
Expected: compile failure — `DeviceEStoppedException`, `emergencyStop`, `resetEStop` do not exist.

- [ ] **Step 9.3: Create the exception**

Create `src/main/java/dev/nocs/safety/DeviceEStoppedException.java`:

```java
package dev.nocs.safety;

public class DeviceEStoppedException extends RuntimeException {

    public DeviceEStoppedException(String deviceId) {
        super("device " + deviceId + " is e-stopped; reset via POST /api/safety/reset before issuing commands");
    }
}
```

- [ ] **Step 9.4: Extend the `Device` interface with default no-ops**

Replace `src/main/java/dev/nocs/device/Device.java`:

```java
package dev.nocs.device;

public interface Device {

    DeviceId id();

    String indiName();

    DeviceKind kind();

    boolean isConnected();

    void connect();

    void disconnect();

    /**
     * Trigger an emergency-stop on this device. Default is a no-op for device kinds whose state machines
     * do not include E_STOPPED (FilterWheel, Focuser). Mount and Camera adapters override this to abort
     * any in-flight motion/exposure and transition to E_STOPPED, after which command methods MUST throw
     * {@link dev.nocs.safety.DeviceEStoppedException} until {@link #resetEStop()} is called.
     */
    default void emergencyStop() {
        // no-op for device kinds without an E_STOPPED state
    }

    /**
     * Clear E_STOPPED on this device. Default is a no-op. Mount/Camera adapters override to transition
     * back to IDLE so command methods stop throwing {@link dev.nocs.safety.DeviceEStoppedException}.
     */
    default void resetEStop() {
        // no-op for device kinds without an E_STOPPED state
    }
}
```

- [ ] **Step 9.5: Override on `IndiMountAdapter` with the guard**

Replace `src/main/java/dev/nocs/device/adapter/IndiMountAdapter.java`:

```java
package dev.nocs.device.adapter;

import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceKind;
import dev.nocs.device.DeviceStateChanged;
import dev.nocs.device.Mount;
import dev.nocs.device.MountState;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.indi.IndiClient;
import dev.nocs.indi.IndiProperty;
import dev.nocs.safety.DeviceEStoppedException;
import java.io.IOException;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

public class IndiMountAdapter implements Mount {

    private final String indiName;
    private final DeviceId id;
    private final IndiClient client;
    private final EventBus bus;
    private final AtomicReference<MountState> state = new AtomicReference<>(MountState.DISCONNECTED);

    public IndiMountAdapter(String indiName, DeviceId id, IndiClient client, EventBus bus) {
        this.indiName = indiName;
        this.id = id;
        this.client = client;
        this.bus = bus;
    }

    @Override
    public DeviceId id() {
        return id;
    }

    @Override
    public String indiName() {
        return indiName;
    }

    @Override
    public DeviceKind kind() {
        return DeviceKind.MOUNT;
    }

    @Override
    public boolean isConnected() {
        return state.get() != MountState.DISCONNECTED;
    }

    @Override
    public MountState state() {
        return state.get();
    }

    @Override
    public void connect() {
        try {
            client.setSwitch(indiName, "CONNECTION", Map.of("CONNECT", true, "DISCONNECT", false));
        } catch (IOException e) {
            throw new RuntimeException("mount connect failed", e);
        }
    }

    @Override
    public void disconnect() {
        try {
            client.setSwitch(indiName, "CONNECTION", Map.of("CONNECT", false, "DISCONNECT", true));
        } catch (IOException e) {
            throw new RuntimeException("mount disconnect failed", e);
        }
    }

    @Override
    public void slew(double raHours, double decDegrees) {
        assertNotEStopped();
        try {
            client.setSwitch(indiName, "ON_COORD_SET", Map.of("SLEW", true, "TRACK", false, "SYNC", false));
            client.setNumber(indiName, "EQUATORIAL_EOD_COORD", Map.of("RA", raHours, "DEC", decDegrees));
        } catch (IOException e) {
            throw new RuntimeException("slew failed", e);
        }
    }

    @Override
    public void syncTo(double raHours, double decDegrees) {
        assertNotEStopped();
        try {
            client.setSwitch(indiName, "ON_COORD_SET", Map.of("SLEW", false, "TRACK", false, "SYNC", true));
            client.setNumber(indiName, "EQUATORIAL_EOD_COORD", Map.of("RA", raHours, "DEC", decDegrees));
        } catch (IOException e) {
            throw new RuntimeException("sync failed", e);
        }
    }

    @Override
    public void park() {
        assertNotEStopped();
        try {
            client.setSwitch(indiName, "TELESCOPE_PARK", Map.of("PARK", true, "UNPARK", false));
        } catch (IOException e) {
            throw new RuntimeException("park failed", e);
        }
    }

    @Override
    public void unpark() {
        assertNotEStopped();
        try {
            client.setSwitch(indiName, "TELESCOPE_PARK", Map.of("PARK", false, "UNPARK", true));
        } catch (IOException e) {
            throw new RuntimeException("unpark failed", e);
        }
    }

    @Override
    public void abort() {
        // Abort is allowed even while E_STOPPED — it is the safe direction.
        try {
            client.setSwitch(indiName, "TELESCOPE_ABORT_MOTION", Map.of("ABORT", true));
        } catch (IOException e) {
            throw new RuntimeException("abort failed", e);
        }
    }

    @Override
    public void emergencyStop() {
        try {
            client.setSwitch(indiName, "TELESCOPE_ABORT_MOTION", Map.of("ABORT", true));
            client.setSwitch(indiName, "TELESCOPE_PARK", Map.of("PARK", true, "UNPARK", false));
        } catch (IOException ignored) {
            // best-effort: still transition to E_STOPPED so commands are blocked
        }
        transition(MountState.E_STOPPED);
    }

    @Override
    public void resetEStop() {
        if (state.get() == MountState.E_STOPPED) {
            transition(MountState.IDLE);
        }
    }

    public void onProperty(IndiProperty p) {
        if (!p.device().equals(indiName)) {
            return;
        }
        if (state.get() == MountState.E_STOPPED) {
            return; // ignore property updates while latched in E_STOPPED
        }
        MountState next = state.get();
        if (p instanceof IndiProperty.SwitchVector sw) {
            if (sw.name().equals("CONNECTION")) {
                boolean connected = Boolean.TRUE.equals(sw.elements().get("CONNECT"));
                next = connected
                        ? (next == MountState.DISCONNECTED ? MountState.IDLE : next)
                        : MountState.DISCONNECTED;
            } else if (sw.name().equals("TELESCOPE_PARK")) {
                if (Boolean.TRUE.equals(sw.elements().get("PARK"))) {
                    next = MountState.PARKED;
                } else if (Boolean.TRUE.equals(sw.elements().get("UNPARK"))) {
                    next = MountState.IDLE;
                }
            }
        } else if (p instanceof IndiProperty.NumberVector n && n.name().equals("EQUATORIAL_EOD_COORD")) {
            next = switch (n.state()) {
                case BUSY -> MountState.SLEWING;
                case OK -> MountState.TRACKING;
                case ALERT -> MountState.ERROR;
                case IDLE -> (state.get() == MountState.SLEWING ? MountState.TRACKING : state.get());
            };
        }
        transition(next);
    }

    private void assertNotEStopped() {
        if (state.get() == MountState.E_STOPPED) {
            throw new DeviceEStoppedException(id.value());
        }
    }

    private void transition(MountState next) {
        MountState prev = state.getAndSet(next);
        if (prev == next) {
            return;
        }
        DeviceStateChanged payload = new DeviceStateChanged(id, DeviceKind.MOUNT, prev.name(), next.name());
        bus.publish(Event.of(Topic.MOUNT, "state_changed", payload.toPayload()));
    }
}
```

- [ ] **Step 9.6: Override on `IndiCameraAdapter` with the guard**

Replace `src/main/java/dev/nocs/device/adapter/IndiCameraAdapter.java`:

```java
package dev.nocs.device.adapter;

import dev.nocs.device.Camera;
import dev.nocs.device.CameraImageSink;
import dev.nocs.device.CameraState;
import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceKind;
import dev.nocs.device.DeviceStateChanged;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.indi.IndiClient;
import dev.nocs.indi.IndiProperty;
import dev.nocs.safety.DeviceEStoppedException;
import java.io.IOException;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

public class IndiCameraAdapter implements Camera {

    private final String indiName;
    private final DeviceId id;
    private final IndiClient client;
    private final EventBus bus;
    private final CameraImageSink sink;
    private final AtomicReference<CameraState> state = new AtomicReference<>(CameraState.DISCONNECTED);
    private volatile Double lastTemp;

    public IndiCameraAdapter(String indiName, DeviceId id, IndiClient client, EventBus bus, CameraImageSink sink) {
        this.indiName = indiName;
        this.id = id;
        this.client = client;
        this.bus = bus;
        this.sink = sink;
    }

    @Override
    public DeviceId id() {
        return id;
    }

    @Override
    public String indiName() {
        return indiName;
    }

    @Override
    public DeviceKind kind() {
        return DeviceKind.CAMERA;
    }

    @Override
    public boolean isConnected() {
        return state.get() != CameraState.DISCONNECTED;
    }

    @Override
    public CameraState state() {
        return state.get();
    }

    @Override
    public Double currentTemperatureCelsius() {
        return lastTemp;
    }

    @Override
    public void connect() {
        try {
            client.setSwitch(indiName, "CONNECTION", Map.of("CONNECT", true, "DISCONNECT", false));
            client.setSwitch(
                    indiName,
                    "UPLOAD_MODE",
                    Map.of("UPLOAD_CLIENT", true, "UPLOAD_LOCAL", false, "UPLOAD_BOTH", false));
            client.enableBlob(indiName, "Also");
        } catch (IOException e) {
            throw new RuntimeException("camera connect failed", e);
        }
    }

    @Override
    public void disconnect() {
        try {
            client.setSwitch(indiName, "CONNECTION", Map.of("CONNECT", false, "DISCONNECT", true));
        } catch (IOException e) {
            throw new RuntimeException("camera disconnect failed", e);
        }
    }

    @Override
    public void cool(double setpointCelsius) {
        assertNotEStopped();
        try {
            client.setSwitch(indiName, "CCD_COOLER", Map.of("COOLER_ON", true, "COOLER_OFF", false));
            client.setNumber(indiName, "CCD_TEMPERATURE", Map.of("CCD_TEMPERATURE_VALUE", setpointCelsius));
        } catch (IOException e) {
            throw new RuntimeException("camera cool failed", e);
        }
    }

    @Override
    public void expose(double durationSeconds) {
        assertNotEStopped();
        try {
            client.setNumber(indiName, "CCD_EXPOSURE", Map.of("CCD_EXPOSURE_VALUE", durationSeconds));
        } catch (IOException e) {
            throw new RuntimeException("expose failed", e);
        }
    }

    @Override
    public void abortExposure() {
        assertNotEStopped();
        try {
            client.setSwitch(indiName, "CCD_ABORT_EXPOSURE", Map.of("ABORT", true));
        } catch (IOException e) {
            throw new RuntimeException("abort exposure failed", e);
        }
    }

    @Override
    public void emergencyStop() {
        try {
            client.setSwitch(indiName, "CCD_ABORT_EXPOSURE", Map.of("ABORT", true));
        } catch (IOException ignored) {
            // best-effort: still transition to E_STOPPED so commands are blocked
        }
        transition(CameraState.E_STOPPED);
    }

    @Override
    public void resetEStop() {
        if (state.get() == CameraState.E_STOPPED) {
            transition(CameraState.IDLE);
        }
    }

    public void onProperty(IndiProperty p) {
        if (!p.device().equals(indiName)) {
            return;
        }
        if (state.get() == CameraState.E_STOPPED) {
            return; // ignore property updates while latched in E_STOPPED
        }
        CameraState next = state.get();
        if (p instanceof IndiProperty.SwitchVector sw && sw.name().equals("CONNECTION")) {
            boolean connected = Boolean.TRUE.equals(sw.elements().get("CONNECT"));
            next = connected
                    ? (next == CameraState.DISCONNECTED ? CameraState.IDLE : next)
                    : CameraState.DISCONNECTED;
        } else if (p instanceof IndiProperty.NumberVector n) {
            if (n.name().equals("CCD_EXPOSURE")) {
                if (n.state() == IndiProperty.State.BUSY) {
                    next = CameraState.EXPOSING;
                } else if (n.state() == IndiProperty.State.ALERT) {
                    next = CameraState.ERROR;
                }
            } else if (n.name().equals("CCD_TEMPERATURE")) {
                Double t = n.elements().get("CCD_TEMPERATURE_VALUE");
                if (t != null) {
                    lastTemp = t;
                }
                if (n.state() == IndiProperty.State.BUSY) {
                    next = CameraState.COOLING;
                } else if (n.state() == IndiProperty.State.OK && state.get() == CameraState.COOLING) {
                    next = CameraState.READY;
                }
            }
        }
        transition(next);
    }

    public void onBlob(byte[] bytes, String format) {
        if (state.get() == CameraState.E_STOPPED) {
            // spec §6.3: a partial download that completes is still saved with e_stopped:true.
            // Plan D will add the FITS header flag; for now we keep the bytes via the sink.
            sink.accept(id, bytes, format == null ? ".fits" : format);
            return;
        }
        CameraState prev = state.getAndSet(CameraState.DOWNLOADING);
        if (prev != CameraState.DOWNLOADING) {
            publishStateEvent(prev, CameraState.DOWNLOADING);
        }
        sink.accept(id, bytes, format == null ? ".fits" : format);
        transition(CameraState.IDLE);
    }

    private void assertNotEStopped() {
        if (state.get() == CameraState.E_STOPPED) {
            throw new DeviceEStoppedException(id.value());
        }
    }

    private void transition(CameraState next) {
        CameraState prev = state.getAndSet(next);
        if (prev == next) {
            return;
        }
        publishStateEvent(prev, next);
    }

    private void publishStateEvent(CameraState prev, CameraState next) {
        DeviceStateChanged payload = new DeviceStateChanged(id, DeviceKind.CAMERA, prev.name(), next.name());
        bus.publish(Event.of(Topic.CAMERA, "state_changed", payload.toPayload()));
    }
}
```

- [ ] **Step 9.7: Run — expect pass + no regressions**

Run: `./gradlew test --tests 'dev.nocs.safety.DeviceEStopGuardTest'`
Expected: three tests pass.

Run the existing device-adapter tests to confirm we did not break Plan B:
Run: `./gradlew test --tests 'dev.nocs.device.*'`
Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 9.8: Commit**

```bash
git add src/main/java/dev/nocs/safety/DeviceEStoppedException.java \
        src/main/java/dev/nocs/device/Device.java \
        src/main/java/dev/nocs/device/adapter/IndiMountAdapter.java \
        src/main/java/dev/nocs/device/adapter/IndiCameraAdapter.java \
        src/test/java/dev/nocs/safety/DeviceEStopGuardTest.java
git commit -m "feat(device): emergencyStop/resetEStop + E_STOPPED command guard"
```

---

### Task 10: `SafetyActionDispatcher`

**Files:**
- Create: `src/main/java/dev/nocs/safety/SafetyActionDispatcher.java`
- Create: `src/test/java/dev/nocs/safety/SafetyActionDispatcherTest.java`

- [ ] **Step 10.1: Write the failing test**

Create `src/test/java/dev/nocs/safety/SafetyActionDispatcherTest.java`:

```java
package dev.nocs.safety;

import dev.nocs.device.Camera;
import dev.nocs.device.CameraState;
import dev.nocs.device.Device;
import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceKind;
import dev.nocs.device.DeviceRegistry;
import dev.nocs.device.Mount;
import dev.nocs.device.MountState;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import java.time.Instant;
import java.util.EnumSet;
import java.util.concurrent.CopyOnWriteArrayList;
import org.junit.jupiter.api.Test;
import reactor.core.Disposable;

import static org.assertj.core.api.Assertions.assertThat;

class SafetyActionDispatcherTest {

    private final EventBus bus = new EventBus();
    private final DeviceRegistry registry = new DeviceRegistry();
    private final RecordingMount mount = new RecordingMount();
    private final RecordingCamera camera = new RecordingCamera();
    private final RecordingSessionLog session = new RecordingSessionLog();
    private final SafetyActionDispatcher dispatcher = new SafetyActionDispatcher(registry, bus, session);

    SafetyActionDispatcherTest() {
        registry.add(mount);
        registry.add(camera);
        mount.connect();
        camera.connect();
    }

    @Test
    void pauseSequenceOnlyEmitsBusEvent() {
        CopyOnWriteArrayList<Event> seen = subscribeAll();
        SafetyRule r = new SafetyRule("paus", new SafetyCondition.HumidityAbove(90), SafetyAction.PAUSE_SEQUENCE);

        dispatcher.dispatch(new TriggeredRule(r, r.condition(), Instant.now()), "rule-trigger");

        assertThat(mount.parked).isZero();
        assertThat(camera.aborted).isZero();
        assertThat(seen.stream().filter(e -> e.topic() == Topic.SEQUENCE && e.type().equals("pause_requested")).count())
                .isEqualTo(1);
        assertThat(seen.stream().filter(e -> e.topic() == Topic.SAFETY && e.type().equals("rule_triggered")).count())
                .isEqualTo(1);
    }

    @Test
    void abortAndParkParksMountsAndEmitsAbort() {
        CopyOnWriteArrayList<Event> seen = subscribeAll();
        SafetyRule r = new SafetyRule("low", new SafetyCondition.AltitudeBelow(20), SafetyAction.ABORT_AND_PARK);

        dispatcher.dispatch(new TriggeredRule(r, r.condition(), Instant.now()), "rule-trigger");

        assertThat(mount.parked).isEqualTo(1);
        assertThat(mount.eStopped).isZero();
        assertThat(camera.aborted).isZero();
        assertThat(seen.stream().filter(e -> e.topic() == Topic.SEQUENCE && e.type().equals("abort_requested")).count())
                .isEqualTo(1);
    }

    @Test
    void eStopAbortsExposuresParksMountsAndTransitionsBoth() {
        CopyOnWriteArrayList<Event> seen = subscribeAll();

        dispatcher.eStop("manual button", "client-1");

        assertThat(camera.aborted).isEqualTo(1);
        assertThat(camera.eStopped).isEqualTo(1);
        assertThat(mount.parked).isEqualTo(1);
        assertThat(mount.eStopped).isEqualTo(1);

        assertThat(seen.stream().filter(e -> e.topic() == Topic.SEQUENCE && e.type().equals("abort_requested")).count())
                .isEqualTo(1);
        assertThat(seen.stream().filter(e -> e.topic() == Topic.SAFETY && e.type().equals("e_stopped")).count())
                .isEqualTo(1);
        assertThat(session.events).anyMatch(e -> e.type.equals("e_stop"));
    }

    @Test
    void resetClearsEStopOnAllDevices() {
        dispatcher.eStop("test", "client-1");
        assertThat(mount.state()).isEqualTo(MountState.E_STOPPED);
        assertThat(camera.state()).isEqualTo(CameraState.E_STOPPED);

        dispatcher.reset("client-1");

        assertThat(mount.state()).isEqualTo(MountState.IDLE);
        assertThat(camera.state()).isEqualTo(CameraState.IDLE);
    }

    private CopyOnWriteArrayList<Event> subscribeAll() {
        CopyOnWriteArrayList<Event> seen = new CopyOnWriteArrayList<>();
        Disposable d = bus.subscribe(EnumSet.allOf(Topic.class)).subscribe(seen::add);
        // Subscription kept for the test lifetime; we never unsubscribe (test is short-lived).
        return seen;
    }

    private static final class RecordingMount implements Mount {
        int parked;
        int eStopped;
        private MountState state = MountState.DISCONNECTED;

        @Override public DeviceId id() { return new DeviceId("mount-rec"); }
        @Override public String indiName() { return "RecMount"; }
        @Override public DeviceKind kind() { return DeviceKind.MOUNT; }
        @Override public boolean isConnected() { return state != MountState.DISCONNECTED; }
        @Override public void connect() { state = MountState.IDLE; }
        @Override public void disconnect() { state = MountState.DISCONNECTED; }
        @Override public MountState state() { return state; }
        @Override public void slew(double r, double d) {}
        @Override public void syncTo(double r, double d) {}
        @Override public void park() { parked++; }
        @Override public void unpark() {}
        @Override public void abort() {}
        @Override public void emergencyStop() { eStopped++; state = MountState.E_STOPPED; }
        @Override public void resetEStop() { if (state == MountState.E_STOPPED) state = MountState.IDLE; }
    }

    private static final class RecordingCamera implements Camera {
        int aborted;
        int eStopped;
        private CameraState state = CameraState.DISCONNECTED;

        @Override public DeviceId id() { return new DeviceId("camera-rec"); }
        @Override public String indiName() { return "RecCcd"; }
        @Override public DeviceKind kind() { return DeviceKind.CAMERA; }
        @Override public boolean isConnected() { return state != CameraState.DISCONNECTED; }
        @Override public void connect() { state = CameraState.IDLE; }
        @Override public void disconnect() { state = CameraState.DISCONNECTED; }
        @Override public CameraState state() { return state; }
        @Override public void cool(double s) {}
        @Override public void expose(double s) {}
        @Override public void abortExposure() { aborted++; }
        @Override public Double currentTemperatureCelsius() { return null; }
        @Override public void emergencyStop() { eStopped++; state = CameraState.E_STOPPED; }
        @Override public void resetEStop() { if (state == CameraState.E_STOPPED) state = CameraState.IDLE; }
    }

    static final class LoggedEvent {
        final String topic;
        final String type;
        final java.util.Map<String, Object> payload;
        LoggedEvent(String topic, String type, java.util.Map<String, Object> payload) {
            this.topic = topic;
            this.type = type;
            this.payload = payload;
        }
    }

    static final class RecordingSessionLog implements SessionLogSink {
        final java.util.List<LoggedEvent> events = new java.util.ArrayList<>();

        @Override
        public void log(String topic, String type, java.util.Map<String, Object> payload) {
            events.add(new LoggedEvent(topic, type, payload));
        }
    }
}
```

> The test introduces `SessionLogSink` (a tiny abstraction over `SessionService.logEvent`) so the dispatcher does not have to depend on the entire `SessionService` (which depends on `JdbcTemplate`). The next step adds the interface; `SafetyService` will provide a real adapter that delegates to `SessionService`.

- [ ] **Step 10.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.safety.SafetyActionDispatcherTest'`
Expected: compile failure — `SafetyActionDispatcher` and `SessionLogSink` do not exist.

- [ ] **Step 10.3: Implement `SessionLogSink` + `SafetyActionDispatcher`**

Create `src/main/java/dev/nocs/safety/SessionLogSink.java`:

```java
package dev.nocs.safety;

import java.util.Map;

@FunctionalInterface
public interface SessionLogSink {

    void log(String topic, String type, Map<String, Object> payload);

    SessionLogSink NOOP = (t, ty, p) -> {};
}
```

Create `src/main/java/dev/nocs/safety/SafetyActionDispatcher.java`:

```java
package dev.nocs.safety;

import dev.nocs.device.Camera;
import dev.nocs.device.Device;
import dev.nocs.device.DeviceKind;
import dev.nocs.device.DeviceRegistry;
import dev.nocs.device.Mount;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import java.util.LinkedHashMap;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class SafetyActionDispatcher {

    private static final Logger log = LoggerFactory.getLogger(SafetyActionDispatcher.class);

    private final DeviceRegistry registry;
    private final EventBus bus;
    private final SessionLogSink sessionLog;

    public SafetyActionDispatcher(DeviceRegistry registry, EventBus bus, SessionLogSink sessionLog) {
        this.registry = registry;
        this.bus = bus;
        this.sessionLog = sessionLog == null ? SessionLogSink.NOOP : sessionLog;
    }

    public void dispatch(TriggeredRule trigger, String caller) {
        SafetyRule rule = trigger.rule();
        Map<String, Object> ruleEvent = new LinkedHashMap<>();
        ruleEvent.put("rule", rule.name());
        ruleEvent.put("action", rule.action().wire());
        ruleEvent.put("caller", caller);
        bus.publish(Event.of(Topic.SAFETY, "rule_triggered", ruleEvent));
        sessionLog.log(Topic.SAFETY.wire(), "rule_triggered", ruleEvent);

        switch (rule.action()) {
            case PAUSE_SEQUENCE -> publishSequence("pause_requested", "rule:" + rule.name(), caller);
            case ABORT_AND_PARK -> {
                publishSequence("abort_requested", "rule:" + rule.name(), caller);
                forEachMount(this::safePark);
            }
            case E_STOP -> eStop("rule:" + rule.name(), caller);
        }
    }

    public void eStop(String reason, String caller) {
        Map<String, Object> payload = Map.of(
                "reason", reason == null ? "manual" : reason,
                "caller", caller == null ? "unknown" : caller);

        forEachCamera(this::safeAbortExposure);
        forEachCamera(Device::emergencyStop);
        forEachMount(this::safePark);
        forEachMount(Device::emergencyStop);

        publishSequence("abort_requested", reason == null ? "e_stop" : reason, caller);
        bus.publish(Event.of(Topic.SAFETY, "e_stopped", payload));
        sessionLog.log(Topic.SAFETY.wire(), "e_stop", payload);
    }

    public void reset(String caller) {
        for (Device d : registry.all()) {
            try {
                d.resetEStop();
            } catch (RuntimeException e) {
                log.warn("device {} resetEStop failed: {}", d.id().value(), e.getMessage());
            }
        }
        Map<String, Object> payload = Map.of("caller", caller == null ? "unknown" : caller);
        bus.publish(Event.of(Topic.SAFETY, "reset", payload));
        sessionLog.log(Topic.SAFETY.wire(), "reset", payload);
    }

    private void publishSequence(String type, String reason, String caller) {
        Map<String, Object> payload = Map.of(
                "reason", reason == null ? "" : reason,
                "caller", caller == null ? "unknown" : caller);
        bus.publish(Event.of(Topic.SEQUENCE, type, payload));
    }

    private void forEachMount(java.util.function.Consumer<Mount> fn) {
        for (Device d : registry.all()) {
            if (d.kind() == DeviceKind.MOUNT && d.isConnected() && d instanceof Mount m) {
                fn.accept(m);
            }
        }
    }

    private void forEachCamera(java.util.function.Consumer<Camera> fn) {
        for (Device d : registry.all()) {
            if (d.kind() == DeviceKind.CAMERA && d.isConnected() && d instanceof Camera c) {
                fn.accept(c);
            }
        }
    }

    private void safePark(Mount m) {
        try {
            m.park();
        } catch (RuntimeException e) {
            log.warn("mount {} park failed: {}", m.id().value(), e.getMessage());
        }
    }

    private void safeAbortExposure(Camera c) {
        try {
            c.abortExposure();
        } catch (RuntimeException e) {
            log.warn("camera {} abort failed: {}", c.id().value(), e.getMessage());
        }
    }
}
```

- [ ] **Step 10.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.safety.SafetyActionDispatcherTest'`
Expected: four tests pass.

- [ ] **Step 10.5: Commit**

```bash
git add src/main/java/dev/nocs/safety/SessionLogSink.java \
        src/main/java/dev/nocs/safety/SafetyActionDispatcher.java \
        src/test/java/dev/nocs/safety/SafetyActionDispatcherTest.java
git commit -m "feat(safety): SafetyActionDispatcher (pause/abort/e-stop/reset effects)"
```

---

### Task 11: `SafetyService` orchestrator + scheduler + bean wiring

**Files:**
- Create: `src/main/java/dev/nocs/safety/SafetyService.java`
- Modify: `src/main/java/dev/nocs/config/AppBeansConfig.java`
- Modify: `src/main/java/dev/nocs/NocsApplication.java`
- Create: `src/test/java/dev/nocs/safety/SafetyServiceTest.java`

- [ ] **Step 11.1: Write the failing test**

Create `src/test/java/dev/nocs/safety/SafetyServiceTest.java`:

```java
package dev.nocs.safety;

import dev.nocs.astronomy.GeographicLocation;
import dev.nocs.device.DeviceRegistry;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.observatory.Observatory;
import dev.nocs.observatory.ObservatoryService;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.EnumSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.CopyOnWriteArrayList;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import reactor.core.Disposable;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class SafetyServiceTest {

    @Test
    void postReadingTriggersMatchingRule(@TempDir Path tmp) throws Exception {
        Path rules = tmp.resolve("safety.yaml");
        Files.writeString(rules, """
                rules:
                  - name: rain
                    when: { rain_detected: true }
                    then: e_stop
                """);

        EventBus bus = new EventBus();
        RecordingDispatcher dispatcher = new RecordingDispatcher();
        SafetyService svc = newService(bus, dispatcher, rules);
        svc.reload();

        svc.postReading(new SensorReading("weather", Instant.now(), Map.of("rain_detected", true)), "test");

        assertThat(dispatcher.triggered).hasSize(1);
        assertThat(dispatcher.triggered.get(0).rule().name()).isEqualTo("rain");
    }

    @Test
    void readingsArrivingViaBusAreEvaluated(@TempDir Path tmp) throws Exception {
        Path rules = tmp.resolve("safety.yaml");
        Files.writeString(rules, """
                rules:
                  - name: hum
                    when: { humidity_above: 90 }
                    then: pause_sequence
                """);

        EventBus bus = new EventBus();
        RecordingDispatcher dispatcher = new RecordingDispatcher();
        SafetyService svc = newService(bus, dispatcher, rules);
        svc.start(); // wire bus subscription + scheduler (since we are not in Spring)
        try {
            bus.publish(Event.of(Topic.SENSOR, "reading",
                    Map.of("sensor", "weather", "ts", "2026-04-22T10:00:00Z",
                            "values", Map.of("humidity", 95.0))));

            Awaitility().untilAsserted(() -> assertThat(dispatcher.triggered).hasSize(1));
        } finally {
            svc.stop();
        }
    }

    @Test
    void eStopBypassesRulesAndCallsDispatcher(@TempDir Path tmp) throws Exception {
        Path rules = tmp.resolve("safety.yaml");
        Files.writeString(rules, "rules: []\n");

        EventBus bus = new EventBus();
        RecordingDispatcher dispatcher = new RecordingDispatcher();
        SafetyService svc = newService(bus, dispatcher, rules);
        svc.reload();

        svc.eStop("manual", "client-1");

        assertThat(dispatcher.eStopReasons).containsExactly("manual");
        assertThat(dispatcher.eStopCallers).containsExactly("client-1");
    }

    @Test
    void reloadFromMissingFileGivesEmptyRulesList(@TempDir Path tmp) {
        EventBus bus = new EventBus();
        RecordingDispatcher dispatcher = new RecordingDispatcher();
        Path rules = tmp.resolve("nope.yaml");
        SafetyService svc = newService(bus, dispatcher, rules);

        svc.reload();
        assertThat(svc.rules()).isEmpty();
    }

    @Test
    void invalidYamlReloadKeepsExistingRules(@TempDir Path tmp) throws Exception {
        Path rules = tmp.resolve("safety.yaml");
        Files.writeString(rules, """
                rules:
                  - name: rain
                    when: { rain_detected: true }
                    then: e_stop
                """);

        EventBus bus = new EventBus();
        SafetyService svc = newService(bus, new RecordingDispatcher(), rules);
        svc.reload();
        assertThat(svc.rules()).hasSize(1);

        Files.writeString(rules, "rules:\n  - name: x\n    then: nuke_everything\n");
        assertThatThrownBy(svc::reload).isInstanceOf(IllegalArgumentException.class);
        assertThat(svc.rules()).hasSize(1);
    }

    @Test
    void altitudeEvaluatorTriggersAltitudeBelowRule(@TempDir Path tmp) throws Exception {
        Path rules = tmp.resolve("safety.yaml");
        Files.writeString(rules, """
                rules:
                  - name: low
                    when: { altitude_below: 30 }
                    then: abort_and_park
                """);

        EventBus bus = new EventBus();
        RecordingDispatcher dispatcher = new RecordingDispatcher();
        ObservatoryService obs = mock(ObservatoryService.class);
        when(obs.activeLocation()).thenReturn(Optional.of(new GeographicLocation(45.0, 0.0, 0.0)));
        when(obs.active()).thenReturn(Optional.of(
                new Observatory(1, "Test", 45.0, 0.0, 0.0, "UTC", "[]", true)));

        SafetyService svc = new SafetyService(bus, dispatcher, new SafetyRuleEngine(),
                new SafetyState(), new SafetyRuleParser(), obs, rules, 60_000L, 60L);
        svc.reload();
        // Direct: an active target whose computed altitude will be below the threshold.
        // Pick a target near the south celestial pole at lat=45 → altitude is below horizon
        // (negative), guaranteed below 30 deg.
        svc.setActiveTarget(new ActiveTarget("synthetic:south", 0.0, -89.9, Instant.now()), "test");
        svc.evaluateAltitudeNow();

        assertThat(dispatcher.triggered).extracting(t -> t.rule().name()).contains("low");
    }

    private SafetyService newService(EventBus bus, RecordingDispatcher dispatcher, Path rulesPath) {
        ObservatoryService obs = mock(ObservatoryService.class);
        when(obs.activeLocation()).thenReturn(Optional.empty());
        return new SafetyService(bus, dispatcher, new SafetyRuleEngine(), new SafetyState(),
                new SafetyRuleParser(), obs, rulesPath, 60_000L, 60L);
    }

    private org.awaitility.core.ConditionFactory Awaitility() {
        return org.awaitility.Awaitility.await().atMost(java.time.Duration.ofSeconds(5));
    }

    static final class RecordingDispatcher extends SafetyActionDispatcher {
        final java.util.List<TriggeredRule> triggered = new CopyOnWriteArrayList<>();
        final java.util.List<String> eStopReasons = new CopyOnWriteArrayList<>();
        final java.util.List<String> eStopCallers = new CopyOnWriteArrayList<>();
        final java.util.List<String> resetCallers = new CopyOnWriteArrayList<>();

        RecordingDispatcher() {
            super(new DeviceRegistry(), new EventBus(), SessionLogSink.NOOP);
        }
        @Override
        public void dispatch(TriggeredRule trigger, String caller) {
            triggered.add(trigger);
        }
        @Override
        public void eStop(String reason, String caller) {
            eStopReasons.add(reason);
            eStopCallers.add(caller);
        }
        @Override
        public void reset(String caller) {
            resetCallers.add(caller);
        }
    }
}
```

- [ ] **Step 11.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.safety.SafetyServiceTest'`
Expected: compile failure — `SafetyService` does not exist.

- [ ] **Step 11.3: Implement `SafetyService`**

Create `src/main/java/dev/nocs/safety/SafetyService.java`:

```java
package dev.nocs.safety;

import dev.nocs.astronomy.GeographicLocation;
import dev.nocs.astronomy.Horizontal;
import dev.nocs.astronomy.Precession;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.observatory.ObservatoryService;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.EnumSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import reactor.core.Disposable;

public class SafetyService {

    private static final Logger log = LoggerFactory.getLogger(SafetyService.class);

    private final EventBus bus;
    private final SafetyActionDispatcher dispatcher;
    private final SafetyRuleEngine engine;
    private final SafetyState state;
    private final SafetyRuleParser parser;
    private final ObservatoryService observatoryService;
    private final Path rulesPath;
    private final long altitudeIntervalMs;
    private final long sensorOfflineDefaultSeconds;

    private final AtomicReference<List<SafetyRule>> rules = new AtomicReference<>(List.of());
    private final ScheduledExecutorService scheduler =
            Executors.newSingleThreadScheduledExecutor(r -> {
                Thread t = new Thread(r, "safety-altitude-eval");
                t.setDaemon(true);
                return t;
            });
    private Disposable subscription;

    public SafetyService(
            EventBus bus,
            SafetyActionDispatcher dispatcher,
            SafetyRuleEngine engine,
            SafetyState state,
            SafetyRuleParser parser,
            ObservatoryService observatoryService,
            Path rulesPath,
            long altitudeIntervalMs,
            long sensorOfflineDefaultSeconds) {
        this.bus = bus;
        this.dispatcher = dispatcher;
        this.engine = engine;
        this.state = state;
        this.parser = parser;
        this.observatoryService = observatoryService;
        this.rulesPath = rulesPath;
        this.altitudeIntervalMs = altitudeIntervalMs;
        this.sensorOfflineDefaultSeconds = sensorOfflineDefaultSeconds;
    }

    @PostConstruct
    public void start() {
        subscription = bus.subscribe(EnumSet.of(Topic.SENSOR, Topic.SEQUENCE)).subscribe(this::onBusEvent,
                e -> log.warn("safety bus subscription error", e));
        scheduler.scheduleAtFixedRate(this::evaluateAltitudeNow,
                altitudeIntervalMs, altitudeIntervalMs, TimeUnit.MILLISECONDS);
        try {
            reload();
        } catch (RuntimeException e) {
            log.warn("safety rules failed to load on startup: {}", e.getMessage());
        }
    }

    @PreDestroy
    public void stop() {
        if (subscription != null) {
            subscription.dispose();
        }
        scheduler.shutdownNow();
    }

    public synchronized void reload() {
        if (rulesPath == null || !Files.exists(rulesPath)) {
            rules.set(List.of());
            log.info("safety rules path missing or empty; rule engine inactive ({})", rulesPath);
            return;
        }
        try {
            List<SafetyRule> parsed = parser.parse(Files.newInputStream(rulesPath));
            rules.set(parsed);
            log.info("safety rules loaded: {} rules from {}", parsed.size(), rulesPath);
        } catch (IOException e) {
            throw new IllegalStateException("could not read " + rulesPath, e);
        }
    }

    public List<SafetyRule> rules() {
        return rules.get();
    }

    public SafetyState stateSnapshot() {
        return state;
    }

    public void postReading(SensorReading reading, String caller) {
        state.recordReading(reading);
        bus.publish(Event.of(Topic.SENSOR, "reading", Map.of(
                "sensor", reading.sensor(),
                "ts", reading.ts().toString(),
                "values", reading.values(),
                "caller", caller == null ? "unknown" : caller)));
        evaluate(caller);
    }

    public void setActiveTarget(ActiveTarget target, String caller) {
        state.setActiveTarget(target);
        evaluateAltitudeNow();
        if (target != null) {
            bus.publish(Event.of(Topic.SEQUENCE, "target_active", Map.of(
                    "target_id", target.targetId(),
                    "ra_j2000_deg", target.raJ2000Deg(),
                    "dec_j2000_deg", target.decJ2000Deg(),
                    "caller", caller == null ? "unknown" : caller)));
        }
    }

    public void eStop(String reason, String caller) {
        dispatcher.eStop(reason, caller);
    }

    public void reset(String caller) {
        state.unlatchAll();
        dispatcher.reset(caller);
    }

    public void evaluateAltitudeNow() {
        Optional<ActiveTarget> at = state.activeTarget();
        if (at.isEmpty()) {
            state.setLastAltitudeDeg(null);
            return;
        }
        Optional<GeographicLocation> loc = observatoryService.activeLocation();
        if (loc.isEmpty()) {
            state.setLastAltitudeDeg(null);
            return;
        }
        Instant now = Instant.now();
        double[] jnow = Precession.precessFromJ2000(at.get().raJ2000Deg(), at.get().decJ2000Deg(), now);
        double[] altaz = Horizontal.equatorialToHorizontal(jnow[0], jnow[1], loc.get(), now, true);
        state.setLastAltitudeDeg(altaz[0]);
        evaluate("scheduler");
    }

    private void evaluate(String caller) {
        List<SafetyRule> snapshot = rules.get();
        if (snapshot.isEmpty()) {
            return;
        }
        List<TriggeredRule> fired = engine.evaluate(state, snapshot);
        for (TriggeredRule t : fired) {
            dispatcher.dispatch(t, caller);
        }
    }

    private void onBusEvent(Event event) {
        if (event.topic() == Topic.SENSOR && "reading".equals(event.type())) {
            ingestSensorEvent(event);
        } else if (event.topic() == Topic.SEQUENCE && "target_active".equals(event.type())) {
            ingestActiveTargetEvent(event);
        }
    }

    @SuppressWarnings("unchecked")
    private void ingestSensorEvent(Event event) {
        Object sensor = event.payload().get("sensor");
        Object values = event.payload().get("values");
        Object caller = event.payload().get("caller");
        if (!(sensor instanceof String s) || !(values instanceof Map<?, ?> v)) {
            return;
        }
        Instant ts = parseTs(event.payload().get("ts"));
        SensorReading r = new SensorReading(s, ts, (Map<String, Object>) v);
        // Avoid double-publish: only update state + evaluate.
        state.recordReading(r);
        evaluate(caller == null ? "bus" : caller.toString());
    }

    private void ingestActiveTargetEvent(Event event) {
        Object idObj = event.payload().get("target_id");
        Object raObj = event.payload().get("ra_j2000_deg");
        Object decObj = event.payload().get("dec_j2000_deg");
        if (!(idObj instanceof String id) || !(raObj instanceof Number ra) || !(decObj instanceof Number dec)) {
            return;
        }
        state.setActiveTarget(new ActiveTarget(id, ra.doubleValue(), dec.doubleValue(), Instant.now()));
        evaluateAltitudeNow();
    }

    private Instant parseTs(Object raw) {
        if (raw instanceof String s) {
            try {
                return Instant.parse(s);
            } catch (Exception ignored) {
                // fall through
            }
        }
        return Instant.now();
    }

    public long sensorOfflineDefaultSeconds() {
        return sensorOfflineDefaultSeconds;
    }
}
```

- [ ] **Step 11.4: Wire beans**

Replace `src/main/java/dev/nocs/config/AppBeansConfig.java`:

```java
package dev.nocs.config;

import dev.nocs.device.CameraImageSink;
import dev.nocs.device.DeviceService;
import dev.nocs.device.TempDirCameraImageSink;
import dev.nocs.events.EventBus;
import dev.nocs.indi.IndiClient;
import dev.nocs.indi.IndiConfig;
import dev.nocs.indi.IndiServerSupervisor;
import dev.nocs.observatory.ObservatoryService;
import dev.nocs.safety.SafetyActionDispatcher;
import dev.nocs.safety.SafetyRuleEngine;
import dev.nocs.safety.SafetyRuleParser;
import dev.nocs.safety.SafetyService;
import dev.nocs.safety.SafetyState;
import dev.nocs.safety.SessionLogSink;
import dev.nocs.session.SessionService;
import dev.nocs.target.SimbadResolver;
import dev.nocs.target.Target;
import dev.nocs.target.catalog.CatalogLoader;
import dev.nocs.target.catalog.InMemoryTargetIndex;
import dev.nocs.target.catalog.SolarSystemCatalog;
import java.io.IOException;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class AppBeansConfig {

    @Bean
    IndiClient indiClient() {
        return new IndiClient();
    }

    @Bean
    CameraImageSink cameraImageSink(NocsProperties props, EventBus bus) {
        String dataDir = props.dataDir() != null ? props.dataDir() : System.getProperty("java.io.tmpdir");
        return new TempDirCameraImageSink(Path.of(dataDir), bus);
    }

    @Bean
    DeviceService deviceService(IndiClient client, EventBus bus, CameraImageSink sink) {
        return new DeviceService(client, bus, sink);
    }

    @Bean
    IndiServerSupervisor indiServerSupervisor(NocsProperties props, EventBus bus) {
        IndiConfig cfg =
                props.indi() != null
                        ? props.indi()
                        : new IndiConfig(IndiConfig.Mode.DISABLED, "127.0.0.1", 7624, List.of(), null);
        return new IndiServerSupervisor(cfg, bus);
    }

    @Bean
    InMemoryTargetIndex bundledTargetIndex() throws IOException {
        List<Target> all = new ArrayList<>();
        all.addAll(CatalogLoader.loadFromClasspath(
                Thread.currentThread().getContextClassLoader(),
                List.of(
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

    @Bean
    SafetyState safetyState() {
        return new SafetyState();
    }

    @Bean
    SafetyRuleEngine safetyRuleEngine() {
        return new SafetyRuleEngine();
    }

    @Bean
    SafetyRuleParser safetyRuleParser() {
        return new SafetyRuleParser();
    }

    @Bean
    SessionLogSink sessionLogSink(SessionService sessions) {
        return (topic, type, payload) -> sessions.logEvent(topic, type, payload);
    }

    @Bean
    SafetyActionDispatcher safetyActionDispatcher(
            DeviceService deviceService, EventBus bus, SessionLogSink sessionLog) {
        return new SafetyActionDispatcher(deviceService.registry(), bus, sessionLog);
    }

    @Bean
    SafetyService safetyService(
            EventBus bus,
            SafetyActionDispatcher dispatcher,
            SafetyRuleEngine engine,
            SafetyState state,
            SafetyRuleParser parser,
            ObservatoryService observatoryService,
            NocsProperties props) {
        Path rulesPath = resolveSafetyPath(props);
        long altitudeMs = props.safety() == null ? 10_000L : props.safety().altitudeEvalIntervalMs();
        long offlineSec = props.safety() == null ? 60L : props.safety().sensorOfflineDefaultSeconds();
        return new SafetyService(bus, dispatcher, engine, state, parser, observatoryService,
                rulesPath, altitudeMs, offlineSec);
    }

    private static Path resolveSafetyPath(NocsProperties props) {
        String configured = props.safety() == null ? null : props.safety().rulesPath();
        if (configured != null && !configured.isBlank()) {
            return Paths.get(configured);
        }
        String dataDir = props.dataDir();
        if (dataDir == null || dataDir.isBlank()) {
            dataDir = System.getProperty("java.io.tmpdir");
        }
        return Paths.get(dataDir).resolve("safety.yaml");
    }
}
```

- [ ] **Step 11.5: Run — expect pass + no regressions**

Run: `./gradlew test --tests 'dev.nocs.safety.SafetyServiceTest'`
Expected: six tests pass.

Run: `./gradlew test`
Expected: `BUILD SUCCESSFUL`.

> If `SafetyService.start()` fires from `@PostConstruct` during other Spring tests and they don't have `safety.yaml` on disk, that's fine — `reload()` logs and returns with an empty rule list. No test fails.

- [ ] **Step 11.6: Commit**

```bash
git add src/main/java/dev/nocs/safety/SafetyService.java \
        src/main/java/dev/nocs/config/AppBeansConfig.java \
        src/test/java/dev/nocs/safety/SafetyServiceTest.java
git commit -m "feat(safety): SafetyService orchestrator + scheduler + bean wiring"
```

---

### Task 12: REST surface — `/api/safety/*`

**Files:**
- Create: `src/main/java/dev/nocs/safety/api/dto/EStopRequest.java`
- Create: `src/main/java/dev/nocs/safety/api/dto/SensorReadingRequest.java`
- Create: `src/main/java/dev/nocs/safety/api/dto/ActiveTargetRequest.java`
- Create: `src/main/java/dev/nocs/safety/api/dto/RuleView.java`
- Create: `src/main/java/dev/nocs/safety/api/dto/SafetyStatusView.java`
- Create: `src/main/java/dev/nocs/safety/api/SafetyController.java`
- Create: `src/test/java/dev/nocs/safety/api/SafetyControllerTest.java`

- [ ] **Step 12.1: Write the failing controller test**

Create `src/test/java/dev/nocs/safety/api/SafetyControllerTest.java`:

```java
package dev.nocs.safety.api;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(properties = "nocs.auth.token=t")
class SafetyControllerTest {

    @Autowired
    MockMvc mvc;

    @Test
    void rulesEndpointReturnsArray() throws Exception {
        mvc.perform(get("/api/safety/rules").header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.rules").isArray())
                .andExpect(jsonPath("$.latched").isArray());
    }

    @Test
    void eStopAcceptsEmptyBody() throws Exception {
        mvc.perform(post("/api/safety/e-stop")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isOk());
    }

    @Test
    void resetAcceptsNoBody() throws Exception {
        mvc.perform(post("/api/safety/reset").header("Authorization", "Bearer t"))
                .andExpect(status().isOk());
    }

    @Test
    void sensorReadingValidatesRequiredFields() throws Exception {
        mvc.perform(post("/api/safety/sensors/readings")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"sensor\":\"weather\",\"values\":{\"humidity\":80}}"))
                .andExpect(status().isOk());

        mvc.perform(post("/api/safety/sensors/readings")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"values\":{}}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void activeTargetEndpoint() throws Exception {
        mvc.perform(post("/api/safety/active-target")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"targetId\":\"messier:M31\",\"raJ2000Deg\":10.685,\"decJ2000Deg\":41.269}"))
                .andExpect(status().isOk());
    }

    @Test
    void reloadEndpoint() throws Exception {
        mvc.perform(post("/api/safety/rules/reload").header("Authorization", "Bearer t"))
                .andExpect(status().isOk());
    }

    @Test
    void rulesEndpointRequiresAuth() throws Exception {
        mvc.perform(get("/api/safety/rules"))
                .andExpect(status().isUnauthorized());
    }
}
```

- [ ] **Step 12.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.safety.api.SafetyControllerTest'`
Expected: HTTP 404 (controller not registered) or compile failure.

- [ ] **Step 12.3: Implement DTOs**

Create `src/main/java/dev/nocs/safety/api/dto/EStopRequest.java`:

```java
package dev.nocs.safety.api.dto;

public record EStopRequest(String reason) {}
```

Create `src/main/java/dev/nocs/safety/api/dto/SensorReadingRequest.java`:

```java
package dev.nocs.safety.api.dto;

import java.time.Instant;
import java.util.Map;

public record SensorReadingRequest(String sensor, Instant ts, Map<String, Object> values) {}
```

Create `src/main/java/dev/nocs/safety/api/dto/ActiveTargetRequest.java`:

```java
package dev.nocs.safety.api.dto;

public record ActiveTargetRequest(String targetId, double raJ2000Deg, double decJ2000Deg) {}
```

Create `src/main/java/dev/nocs/safety/api/dto/RuleView.java`:

```java
package dev.nocs.safety.api.dto;

import dev.nocs.safety.SafetyCondition;
import dev.nocs.safety.SafetyRule;
import java.util.LinkedHashMap;
import java.util.Map;

public record RuleView(String name, String action, Map<String, Object> when, boolean latched) {

    public static RuleView of(SafetyRule rule, boolean latched) {
        return new RuleView(rule.name(), rule.action().wire(), conditionMap(rule.condition()), latched);
    }

    private static Map<String, Object> conditionMap(SafetyCondition c) {
        Map<String, Object> out = new LinkedHashMap<>();
        switch (c) {
            case SafetyCondition.HumidityAbove h -> out.put("humidity_above", h.percent());
            case SafetyCondition.RainDetected ignored -> out.put("rain_detected", true);
            case SafetyCondition.AltitudeBelow a -> out.put("altitude_below", a.degrees());
            case SafetyCondition.SensorOffline o -> out.put("sensor_offline",
                    Map.of("sensor", o.sensor(), "threshold_seconds", o.thresholdSeconds()));
        }
        return out;
    }
}
```

Create `src/main/java/dev/nocs/safety/api/dto/SafetyStatusView.java`:

```java
package dev.nocs.safety.api.dto;

import java.util.List;

public record SafetyStatusView(List<RuleView> rules, List<String> latched, String activeTargetId) {}
```

- [ ] **Step 12.4: Implement the controller**

Create `src/main/java/dev/nocs/safety/api/SafetyController.java`:

```java
package dev.nocs.safety.api;

import dev.nocs.safety.ActiveTarget;
import dev.nocs.safety.SafetyRule;
import dev.nocs.safety.SafetyService;
import dev.nocs.safety.SensorReading;
import dev.nocs.safety.api.dto.ActiveTargetRequest;
import dev.nocs.safety.api.dto.EStopRequest;
import dev.nocs.safety.api.dto.RuleView;
import dev.nocs.safety.api.dto.SafetyStatusView;
import dev.nocs.safety.api.dto.SensorReadingRequest;
import jakarta.servlet.http.HttpServletRequest;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/safety")
public class SafetyController {

    private final SafetyService service;

    public SafetyController(SafetyService service) {
        this.service = service;
    }

    @GetMapping("/rules")
    public SafetyStatusView rules() {
        List<SafetyRule> loaded = service.rules();
        List<RuleView> views = loaded.stream()
                .map(r -> RuleView.of(r, service.stateSnapshot().isLatched(r.name())))
                .toList();
        return new SafetyStatusView(
                views,
                List.copyOf(service.stateSnapshot().latchedRules()),
                service.stateSnapshot().activeTarget().map(ActiveTarget::targetId).orElse(null));
    }

    @PostMapping("/rules/reload")
    public Map<String, Object> reload() {
        service.reload();
        return Map.of("rules", service.rules().size());
    }

    @PostMapping("/e-stop")
    public Map<String, String> eStop(@RequestBody(required = false) EStopRequest req, HttpServletRequest http) {
        String reason = req == null || req.reason() == null ? "manual" : req.reason();
        service.eStop(reason, callerOf(http));
        return Map.of("status", "ok");
    }

    @PostMapping("/reset")
    public Map<String, String> reset(HttpServletRequest http) {
        service.reset(callerOf(http));
        return Map.of("status", "ok");
    }

    @PostMapping("/sensors/readings")
    public Map<String, String> reading(
            @RequestBody SensorReadingRequest req, HttpServletRequest http) {
        if (req == null || req.sensor() == null || req.sensor().isBlank()) {
            throw new IllegalArgumentException("sensor is required");
        }
        Instant ts = req.ts() == null ? Instant.now() : req.ts();
        service.postReading(new SensorReading(req.sensor(), ts, req.values()), callerOf(http));
        return Map.of("status", "ok");
    }

    @PostMapping("/active-target")
    public Map<String, String> activeTarget(
            @RequestBody ActiveTargetRequest req, HttpServletRequest http) {
        if (req == null || req.targetId() == null || req.targetId().isBlank()) {
            throw new IllegalArgumentException("targetId is required");
        }
        service.setActiveTarget(
                new ActiveTarget(req.targetId(), req.raJ2000Deg(), req.decJ2000Deg(), Instant.now()),
                callerOf(http));
        return Map.of("status", "ok");
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, String>> badRequest(IllegalArgumentException e) {
        return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
    }

    private static String callerOf(HttpServletRequest http) {
        String addr = http.getRemoteAddr();
        String ua = http.getHeader("User-Agent");
        if (addr == null && ua == null) {
            return "unknown";
        }
        return (addr == null ? "?" : addr) + (ua == null ? "" : " (" + ua + ")");
    }
}
```

- [ ] **Step 12.5: Run — expect pass + no regressions**

Run: `./gradlew test --tests 'dev.nocs.safety.api.SafetyControllerTest'`
Expected: seven tests pass.

Run: `./gradlew test`
Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 12.6: Commit**

```bash
git add src/main/java/dev/nocs/safety/api \
        src/test/java/dev/nocs/safety/api/SafetyControllerTest.java
git commit -m "feat(safety): /api/safety REST surface (rules, e-stop, reset, sensors, active-target)"
```

---

### Task 13: End-to-end integration test

**Files:**
- Create: `src/test/java/dev/nocs/safety/IntegrationSafetyApiTest.java`

This test boots the full Spring context, replaces the live `DeviceRegistry` contents with simulated mount/camera doubles via direct `registry.add(...)`, posts a rain reading, and asserts the dispatcher's effects.

- [ ] **Step 13.1: Write the test**

Create `src/test/java/dev/nocs/safety/IntegrationSafetyApiTest.java`:

```java
package dev.nocs.safety;

import dev.nocs.device.Camera;
import dev.nocs.device.CameraState;
import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceKind;
import dev.nocs.device.DeviceService;
import dev.nocs.device.Mount;
import dev.nocs.device.MountState;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.EnumSet;
import java.util.concurrent.CopyOnWriteArrayList;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import reactor.core.Disposable;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class IntegrationSafetyApiTest {

    @TempDir
    static Path tmp;

    @DynamicPropertySource
    static void rulesPath(DynamicPropertyRegistry reg) throws IOException {
        Path rules = tmp.resolve("safety.yaml");
        Files.writeString(rules, """
                rules:
                  - name: rain
                    when: { rain_detected: true }
                    then: e_stop
                """);
        reg.add("nocs.auth.token", () -> "t");
        reg.add("nocs.safety.rules-path", () -> rules.toString());
    }

    @Autowired MockMvc mvc;
    @Autowired DeviceService deviceService;
    @Autowired EventBus bus;
    @Autowired SafetyService safety;

    private FakeMount mount;
    private FakeCamera camera;
    private Disposable sub;
    private final CopyOnWriteArrayList<Event> seen = new CopyOnWriteArrayList<>();

    @BeforeEach
    void setUp() {
        // Reload because the file path was set via DynamicPropertySource AFTER Spring start.
        safety.reload();
        // Clear stale latches from earlier tests in the same Spring context.
        safety.reset("test-setup");

        mount = new FakeMount();
        camera = new FakeCamera();
        deviceService.registry().add(mount);
        deviceService.registry().add(camera);
        mount.connect();
        camera.connect();

        sub = bus.subscribe(EnumSet.allOf(Topic.class)).subscribe(seen::add);
    }

    @AfterEach
    void tearDown() {
        sub.dispose();
        deviceService.registry().remove(mount.id());
        deviceService.registry().remove(camera.id());
    }

    @Test
    void rainReadingTriggersEStop() throws Exception {
        mvc.perform(post("/api/safety/sensors/readings")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"sensor\":\"weather\",\"values\":{\"rain_detected\":true}}"))
                .andExpect(status().isOk());

        Awaitility.await().atMost(Duration.ofSeconds(5)).untilAsserted(() -> {
            assertThat(camera.aborted).isGreaterThanOrEqualTo(1);
            assertThat(camera.eStopped).isGreaterThanOrEqualTo(1);
            assertThat(mount.parked).isGreaterThanOrEqualTo(1);
            assertThat(mount.eStopped).isGreaterThanOrEqualTo(1);

            assertThat(seen.stream().filter(e -> e.topic() == Topic.SAFETY && "rule_triggered".equals(e.type())).count())
                    .isEqualTo(1);
            assertThat(seen.stream().filter(e -> e.topic() == Topic.SAFETY && "e_stopped".equals(e.type())).count())
                    .isEqualTo(1);
            assertThat(seen.stream().filter(e -> e.topic() == Topic.SEQUENCE && "abort_requested".equals(e.type())).count())
                    .isEqualTo(1);
        });

        mvc.perform(get("/api/safety/rules").header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.rules[0].name").value("rain"))
                .andExpect(jsonPath("$.rules[0].latched").value(true))
                .andExpect(jsonPath("$.latched", org.hamcrest.Matchers.hasItem("rain")));

        // Reset clears latch and device E_STOPPED state.
        mvc.perform(post("/api/safety/reset").header("Authorization", "Bearer t"))
                .andExpect(status().isOk());

        Awaitility.await().atMost(Duration.ofSeconds(2)).untilAsserted(() -> {
            assertThat(mount.state()).isEqualTo(MountState.IDLE);
            assertThat(camera.state()).isEqualTo(CameraState.IDLE);
        });
    }

    private static final class FakeMount implements Mount {
        int parked;
        int eStopped;
        private MountState state = MountState.DISCONNECTED;

        @Override public DeviceId id() { return new DeviceId("itest-mount"); }
        @Override public String indiName() { return "ITestMount"; }
        @Override public DeviceKind kind() { return DeviceKind.MOUNT; }
        @Override public boolean isConnected() { return state != MountState.DISCONNECTED; }
        @Override public void connect() { state = MountState.IDLE; }
        @Override public void disconnect() { state = MountState.DISCONNECTED; }
        @Override public MountState state() { return state; }
        @Override public void slew(double r, double d) {}
        @Override public void syncTo(double r, double d) {}
        @Override public void park() { parked++; }
        @Override public void unpark() {}
        @Override public void abort() {}
        @Override public void emergencyStop() { eStopped++; state = MountState.E_STOPPED; }
        @Override public void resetEStop() { if (state == MountState.E_STOPPED) state = MountState.IDLE; }
    }

    private static final class FakeCamera implements Camera {
        int aborted;
        int eStopped;
        private CameraState state = CameraState.DISCONNECTED;

        @Override public DeviceId id() { return new DeviceId("itest-camera"); }
        @Override public String indiName() { return "ITestCcd"; }
        @Override public DeviceKind kind() { return DeviceKind.CAMERA; }
        @Override public boolean isConnected() { return state != CameraState.DISCONNECTED; }
        @Override public void connect() { state = CameraState.IDLE; }
        @Override public void disconnect() { state = CameraState.DISCONNECTED; }
        @Override public CameraState state() { return state; }
        @Override public void cool(double s) {}
        @Override public void expose(double s) {}
        @Override public void abortExposure() { aborted++; }
        @Override public Double currentTemperatureCelsius() { return null; }
        @Override public void emergencyStop() { eStopped++; state = CameraState.E_STOPPED; }
        @Override public void resetEStop() { if (state == CameraState.E_STOPPED) state = CameraState.IDLE; }
    }
}
```

- [ ] **Step 13.2: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.safety.IntegrationSafetyApiTest'`
Expected: one test passes (and may take ~5 s due to Spring boot + Awaitility).

Run the full suite to confirm no regressions:
Run: `./gradlew test`
Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 13.3: Commit**

```bash
git add src/test/java/dev/nocs/safety/IntegrationSafetyApiTest.java
git commit -m "test(safety): end-to-end integration covering rain rule + e-stop + reset"
```

---

### Task 14: Documentation + decomposition status

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-04-22-v0.1-plan-decomposition.md`

- [ ] **Step 14.1: Add a Safety section to the README**

Append to `README.md` (under the existing "Operations" or feature list — if there is no such section, add one near the bottom):

```markdown
## Safety (Plan F)

NOCS ships a YAML rule engine plus an always-available emergency stop:

- `safety.yaml` lives in your data dir (copied from `safety.example.yaml` on first run). Reload after edits:
  `curl -X POST -H 'Authorization: Bearer <token>' http://localhost:8080/api/safety/rules/reload`.
- Supported conditions: `humidity_above`, `rain_detected`, `altitude_below`, `sensor_offline`.
- Supported actions: `pause_sequence`, `abort_and_park`, `e_stop`.
- Push a sensor reading (e.g. from your weather script):
  `curl -X POST -H 'Authorization: Bearer <token>' -H 'Content-Type: application/json' \
       http://localhost:8080/api/safety/sensors/readings \
       -d '{"sensor":"weather","values":{"rain_detected":true}}'`.
- Emergency stop:
  `curl -X POST -H 'Authorization: Bearer <token>' http://localhost:8080/api/safety/e-stop`.
- After an E-stop, devices stay in `E_STOPPED` and reject commands until you reset:
  `curl -X POST -H 'Authorization: Bearer <token>' http://localhost:8080/api/safety/reset`.
```

- [ ] **Step 14.2: Mark Plan F written in the decomposition table**

In `docs/superpowers/plans/2026-04-22-v0.1-plan-decomposition.md`:

1. In the "Plan overview" table, replace the row for **F** with:

```
| **F** | SafetyService | A, B | YAML rule engine + `POST /api/safety/e-stop`; simulated sensor event triggers park / sequence abort per spec. Implemented: [2026-04-22-nocs-safety-service.md](./2026-04-22-nocs-safety-service.md). |
```

2. In the "Current status" table, replace the `D–I | No` row with two rows:

```
| F | Yes | [2026-04-22-nocs-safety-service.md](./2026-04-22-nocs-safety-service.md) |
| D, E, G, H, I | No | Author with the `writing-plans` skill when starting that slice |
```

- [ ] **Step 14.3: Run the full suite once more**

Run: `./gradlew test`
Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 14.4: Commit**

```bash
git add README.md docs/superpowers/plans/2026-04-22-v0.1-plan-decomposition.md
git commit -m "docs: README safety section + decomposition table marks Plan F written"
```

---

## Self-review

Before declaring this plan ready, the author (or any subagent picking it up) should run the following checks. They are mechanical — no taste required.

**Spec coverage (§6 + §8.2 + §13 + §18 #5):**

- [ ] §6.1 conditions `humidity_above`, `rain_detected`, `altitude_below`, `sensor_offline` — covered by Task 4 + 5 + 8.
- [ ] §6.1 actions `pause_sequence`, `abort_and_park`, `e_stop` — covered by Task 3 + 10.
- [ ] §6.1 idempotent re-fire — covered by Task 8.
- [ ] §6.2 "no watchdog in v0.1" — explicit non-goal in scope section.
- [ ] §6.3 E-stop effects (abort exposure, stop sequence, park mount, halt cooling, emit event, log caller) — Task 10 (effects + dispatcher) + Task 11 (`SessionLogSink` wiring) + Task 12 (`callerOf`).
- [ ] §6.4 device state machines + `E_STOPPED` — already in Plan B; Task 9 adds the guard.
- [ ] §8.2 endpoints — Task 12.
- [ ] §13 SafetyService inventory + WeatherService stubbed pattern — `SENSOR` topic + `POST /api/safety/sensors/readings` give the same ingress for tests and a future driver.
- [ ] §18 #5 reset endpoint — Task 12 (`POST /api/safety/reset`) + Task 9/10 (device `resetEStop` + dispatcher reset).

**Placeholder scan:** grep the plan for `TBD`, `TODO`, `implement later`, `similar to`, `add appropriate`, `handle edge cases`, `fill in details`. None should appear.

**Type / method-name consistency:**
- `SafetyAction.E_STOP` / `wire()="e_stop"` consistent across Tasks 3, 5, 10, 12.
- `SafetyCondition.HumidityAbove(double percent)` — same field name in Tasks 4, 5, 8, 12 (`RuleView.conditionMap`).
- `SafetyCondition.SensorOffline(sensor, thresholdSeconds)` — YAML key is `threshold_seconds` (snake_case), Java field is `thresholdSeconds`; parser maps between them in Task 5.
- `SafetyService` constructor signature in Task 11 matches the call in `AppBeansConfig.safetyService(...)` and in `SafetyServiceTest.newService(...)`.
- `Mount#emergencyStop()` / `Mount#resetEStop()` declared in Task 9, called in Task 10 (dispatcher), exercised in Tasks 9, 10, 13.
- `Topic.SENSOR` introduced in Task 1, used in Tasks 11, 12, 13.

**Cross-plan boundary check:** This plan does not touch `target/`, `observatory/` write paths, FITS I/O, sequence engine internals, or the web client. It only **calls** `ObservatoryService.activeLocation()` and uses `Horizontal` / `Precession` from Plan C.

If any check fails, fix inline and re-run the relevant test command.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-22-nocs-safety-service.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using `executing-plans`, batch execution with checkpoints.

Which approach?

**If Subagent-Driven chosen:**
- **REQUIRED SUB-SKILL:** Use `superpowers:subagent-driven-development`.
- Fresh subagent per task + two-stage review.

**If Inline Execution chosen:**
- **REQUIRED SUB-SKILL:** Use `superpowers:executing-plans`.
- Batch execution with checkpoints for review.
