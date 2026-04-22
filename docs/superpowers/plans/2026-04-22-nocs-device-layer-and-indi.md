# NOCS Abstract Device Layer + INDI Adapter Implementation Plan (Plan B)

> **See also:** [NOCS v0.1 plan decomposition (A–I)](./2026-04-22-v0.1-plan-decomposition.md) — full roadmap and dependencies.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the abstract device layer (Mount, Camera, FilterWheel, Focuser), a minimal in-house INDI XML-over-TCP client, an `indiserver` child-process supervisor, and device REST controllers so an authenticated client can drive INDI simulator drivers end-to-end (connect, slew/park/sync, cool/expose, filter select, focuser move) via NOCS's own HTTP API, with state-machine events on the bus.

**Architecture:** NOCS launches `indiserver` with a configured set of driver binaries and connects to it as a TCP client speaking INDI's concatenated-XML protocol. A pure-Java `IndiClient` maintains a property registry and exposes a `Flux<PropertyUpdate>` stream. Abstract `Mount`, `Camera`, `FilterWheel`, `Focuser` interfaces are implemented by an **INDI adapter** package that maps NOCS method calls to INDI property writes and maps property updates back to typed state transitions. A `DeviceService` owns the registry of discovered devices; REST controllers delegate to it. Camera BLOBs flow through a `CameraImageSink` port whose default impl drops bytes into `data_dir/captures/tmp/` and emits a `camera.image_received` event — Plan D will replace that default with the real `ImageStoreService`. An integration test spins up a real `indiserver` + simulator drivers and exercises the HTTP surface.

**Tech Stack:**
- JDK 25 + Spring Boot 3.5 from Plan A
- Project Reactor (`Sinks.Many`, `Flux`) — already present
- `java.nio.channels.SocketChannel` + `javax.xml.stream.XMLStreamReader` for the INDI client (no new runtime deps)
- `java.util.Base64` for BLOB decoding
- `java.lang.ProcessBuilder` for `indiserver` supervision
- `indi-bin` package on CI (Linux simulators: `indi_simulator_telescope`, `indi_simulator_ccd`, `indi_simulator_focus`, `indi_simulator_wheel`)
- JUnit 5, AssertJ, Awaitility (new test dep) for integration test polling, `MockMvc` for controller tests

## Scope

### In scope for Plan B

1. NOCS config section for INDI (`mode: managed|external`, host/port, driver list, restart backoff).
2. Minimal in-house INDI client (`IndiClient`): connect, read concatenated-XML stream, typed property registry for switch/number/text/BLOB vectors, publish `PropertyUpdate` events, set switch/number/text vectors, enable & receive BLOBs.
3. `IndiServerSupervisor`: start `indiserver` with configured drivers when `mode=managed`, restart on crash with exponential backoff, pipe stdout/stderr into SLF4J, emit `system.indiserver` events.
4. Abstract device layer: `Device` base + `Mount`, `Camera`, `FilterWheel`, `Focuser` interfaces; state enums per §6.4; `DeviceStateChanged` events on the bus.
5. INDI adapter implementations for the four device kinds, mapping to the standard INDI properties used by the simulator drivers and most real drivers.
6. `CameraImageSink` port + default temp-dir implementation; emits `camera.image_received` with a file path.
7. `DeviceService` + `DeviceRegistry`: discover devices from the INDI client, expose list/connect/disconnect.
8. REST controllers per spec §8.2:
   - `GET /api/devices`, `POST /api/devices/{id}/connect`, `POST /api/devices/{id}/disconnect`
   - `POST /api/mounts/{id}/slew`, `/park`, `/sync`
   - `POST /api/cameras/{id}/expose`, `/cool`
   - `POST /api/filterwheels/{id}/select`
   - `POST /api/focusers/{id}/move`
9. End-to-end integration test that launches a real `indiserver` with simulator drivers and exercises the REST surface for all four device kinds.
10. CI update: install `indi-bin` on the Linux runner; run the integration test as part of `./gradlew check`.

### Explicitly out of scope for Plan B

- `POST /api/focusers/{id}/autofocus` — autofocus algorithm is part of the imaging workflow (Plan G).
- `ImageStoreService`: FITS + thumbnail persistence, `images` table, `/api/images/*` — that is **Plan D**. Plan B only defines the port and writes to a temp dir.
- Sequence engine / `ImagingService` (Plan G), plate solving (Plan E), safety rule engine (Plan F), target catalogs (Plan C).
- Dithering, autoguiding, meridian flip.
- Windows / arm64 integration testing of `indiserver` — `indi-bin` isn't generally available on Windows runners; we keep the integration test Linux-only for now. Plan I revisits multi-arch.
- Real hardware — only simulator drivers here.

## File Structure

All paths are relative to the repo root (`/home/jorjazo/dev/nocs/nocs`). Each file has one clear responsibility; nothing over ~250 lines.

**New main sources** (`src/main/java/dev/nocs/`):

- `indi/IndiProperty.java` — sealed property model: `SwitchVector`, `NumberVector`, `TextVector`, `BlobVector`.
- `indi/PropertyUpdate.java` — immutable "property N changed" event.
- `indi/IndiXmlCodec.java` — parse one INDI XML message from a reader; serialise outbound messages (`getProperties`, `newSwitchVector`, `newNumberVector`, `newTextVector`, `enableBLOB`).
- `indi/IndiClient.java` — TCP lifecycle, read loop, property registry, `Flux<PropertyUpdate>` publisher, property writes, BLOB handling.
- `indi/IndiServerSupervisor.java` — `ProcessBuilder` lifecycle, restart-with-backoff, log piping.
- `indi/IndiConfig.java` — configuration-properties subrecord (under `nocs.indi`).
- `device/DeviceKind.java` — enum `MOUNT, CAMERA, FILTERWHEEL, FOCUSER, UNKNOWN`.
- `device/DeviceId.java` — stable slug of the INDI device name (e.g. `"telescope-simulator"`).
- `device/Device.java` — common interface: `id()`, `kind()`, `indiName()`, `connect()`, `disconnect()`, `state()`.
- `device/MountState.java`, `device/CameraState.java`, `device/FilterWheelState.java`, `device/FocuserState.java` — enums per spec §6.4.
- `device/Mount.java` — `slew(ra, dec)`, `park()`, `unpark()`, `syncTo(ra, dec)`, `abort()`, `state()`.
- `device/Camera.java` — `cool(setpointC)`, `expose(durationSeconds, binning)`, `abortExposure()`, `state()`, `currentTemperatureC()`.
- `device/FilterWheel.java` — `selectSlot(int)`, `slotNames()`, `currentSlot()`, `state()`.
- `device/Focuser.java` — `moveAbsolute(int)`, `moveRelative(int)`, `currentPosition()`, `abort()`, `state()`.
- `device/CameraImageSink.java` — port: `accept(CameraId, byte[] bytes, String extension)`.
- `device/TempDirCameraImageSink.java` — default implementation: write to `data_dir/captures/tmp/<ts>-<seq>.fits`, emit `camera.image_received` event.
- `device/DeviceStateChanged.java` — record (`DeviceId`, `kind`, `oldState`, `newState`) used as event payload.
- `device/DeviceService.java` — owns `IndiClient`, `IndiServerSupervisor`, the registry of adapters; connect/disconnect/list.
- `device/DeviceRegistry.java` — `Map<DeviceId, Device>` with typed accessors (`mount(id)`, `camera(id)`, …).
- `device/adapter/IndiMountAdapter.java` — implements `Mount` against INDI properties.
- `device/adapter/IndiCameraAdapter.java` — implements `Camera`, consumes `CCD1` BLOB into `CameraImageSink`.
- `device/adapter/IndiFilterWheelAdapter.java`
- `device/adapter/IndiFocuserAdapter.java`
- `device/adapter/IndiDeviceFactory.java` — given an INDI device name + seen property set, decide which `DeviceKind` it is and instantiate an adapter.
- `device/api/DeviceController.java` — `/api/devices`, `/api/devices/{id}/connect`, `/api/devices/{id}/disconnect`.
- `device/api/MountController.java` — `/api/mounts/{id}/…`.
- `device/api/CameraController.java` — `/api/cameras/{id}/…`.
- `device/api/FilterWheelController.java` — `/api/filterwheels/{id}/…`.
- `device/api/FocuserController.java` — `/api/focusers/{id}/…`.
- `device/api/dto/*` — small request/response records (`SlewRequest`, `ExposeRequest`, `CoolRequest`, `SelectSlotRequest`, `MoveRequest`, `DeviceView`).

**Modified main sources:**

- `config/NocsProperties.java` — add `IndiConfig indi` field.
- `config/config.example.yaml` — add `indi:` section.
- `events/Topic.java` — already has `MOUNT`, `CAMERA`, `FILTERWHEEL`, `FOCUSER`, `DEVICE_CONNECTION`, `SYSTEM` — no change needed.

**New test sources** (`src/test/java/dev/nocs/`):

- `indi/IndiXmlCodecTest.java` — parse canned fixtures + round-trip serialisation.
- `indi/IndiClientTest.java` — end-to-end against an in-process fake INDI server (a tiny `ServerSocket`-based test harness that speaks just enough XML).
- `indi/IndiServerSupervisorTest.java` — launches `/bin/cat -n` or `/bin/sleep` as a stand-in when `indiserver` is absent; restart-with-backoff unit tested with a scripted failing process (no INDI required).
- `device/adapter/IndiMountAdapterTest.java`, `IndiCameraAdapterTest.java`, `IndiFilterWheelAdapterTest.java`, `IndiFocuserAdapterTest.java` — each uses a mocked `IndiClient` to verify property reads/writes and state transitions.
- `device/TempDirCameraImageSinkTest.java` — temp dir + event emission.
- `device/api/DeviceControllerTest.java`, `MountControllerTest.java`, `CameraControllerTest.java`, `FilterWheelControllerTest.java`, `FocuserControllerTest.java` — `MockMvc` tests against a mocked `DeviceRegistry`/service.
- `device/IndiSimulatorIntegrationTest.java` — gated on `indi-bin`; spins up a real `indiserver --local --no-multicast -p <port> indi_simulator_*`; walks through connect → slew → expose (verifies BLOB arrived via sink) → filter select → focuser move → disconnect, asserting state events on the bus.

**New resources / scripts:**

- `src/test/resources/indi/fixtures/defSwitchVector.xml`, `defNumberVector.xml`, `defBlobVector.xml`, `setNumberVector.xml`, `setBlobVector.xml` — canned protocol fragments for `IndiXmlCodecTest`.
- `smoke/device-smoke.sh` — optional manual script: starts `indiserver` with simulators, exercises a few REST calls. Not wired to CI (the JUnit integration test covers CI); kept for local development.

**CI:**

- `.github/workflows/ci.yml` — add step `sudo apt-get update && sudo apt-get install -y indi-bin`, set `NOCS_INDI_BIN=1` so the integration test runs.

---

## Tasks

Each task is self-contained: files listed, TDD steps with complete code, exact commands with expected output, and a commit at the end. Tasks 2–5 build the foundation (INDI client + supervisor); 6–11 add device interfaces and adapters; 12 wires DeviceService + REST; 13 is the end-to-end simulator integration test; 14 updates CI; 15 updates the README.

---

### Task 1: Extend config for `nocs.indi.*`

**Files:**
- Modify: `src/main/java/dev/nocs/config/NocsProperties.java`
- Create: `src/main/java/dev/nocs/indi/IndiConfig.java`
- Modify: `src/main/resources/config.example.yaml`
- Modify: `src/main/resources/application.yaml` (add harmless test defaults)
- Create: `src/test/java/dev/nocs/indi/IndiConfigTest.java`

- [ ] **Step 1.1: Write the failing binding test**

Create `src/test/java/dev/nocs/indi/IndiConfigTest.java`:

```java
package dev.nocs.indi;

import dev.nocs.config.NocsProperties;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@TestPropertySource(properties = {
        "nocs.auth.token=t",
        "nocs.indi.mode=external",
        "nocs.indi.host=127.0.0.1",
        "nocs.indi.port=7624",
        "nocs.indi.drivers[0]=indi_simulator_telescope",
        "nocs.indi.drivers[1]=indi_simulator_ccd",
        "nocs.indi.restart.initial-backoff-ms=200",
        "nocs.indi.restart.max-backoff-ms=5000"
})
class IndiConfigTest {

    @Autowired NocsProperties props;

    @Test
    void bindsIndiSection() {
        IndiConfig indi = props.indi();
        assertThat(indi).isNotNull();
        assertThat(indi.mode()).isEqualTo(IndiConfig.Mode.EXTERNAL);
        assertThat(indi.host()).isEqualTo("127.0.0.1");
        assertThat(indi.port()).isEqualTo(7624);
        assertThat(indi.drivers())
                .containsExactly("indi_simulator_telescope", "indi_simulator_ccd");
        assertThat(indi.restart().initialBackoffMs()).isEqualTo(200);
        assertThat(indi.restart().maxBackoffMs()).isEqualTo(5000);
    }
}
```

- [ ] **Step 1.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.indi.IndiConfigTest'`
Expected: compilation fails — `IndiConfig` does not exist.

- [ ] **Step 1.3: Implement `IndiConfig`**

Create `src/main/java/dev/nocs/indi/IndiConfig.java`:

```java
package dev.nocs.indi;

import java.util.List;

public record IndiConfig(
        Mode mode,
        String host,
        Integer port,
        List<String> drivers,
        Restart restart) {

    public enum Mode { MANAGED, EXTERNAL, DISABLED }

    public record Restart(Long initialBackoffMs, Long maxBackoffMs) {
        public Restart {
            if (initialBackoffMs == null) initialBackoffMs = 500L;
            if (maxBackoffMs == null) maxBackoffMs = 30_000L;
        }
    }

    public IndiConfig {
        if (mode == null) mode = Mode.MANAGED;
        if (host == null || host.isBlank()) host = "127.0.0.1";
        if (port == null) port = 7624;
        if (drivers == null) drivers = List.of();
        if (restart == null) restart = new Restart(null, null);
    }
}
```

- [ ] **Step 1.4: Extend `NocsProperties`**

Open `src/main/java/dev/nocs/config/NocsProperties.java` and replace the record declaration with:

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
        IndiConfig indi) {

    public record Auth(String token) {}
    public record Server(String host, Integer port) {}
    public record Datasource(String url) {}
}
```

- [ ] **Step 1.5: Add harmless default to `application.yaml`**

Append to `src/main/resources/application.yaml`:

```yaml
nocs:
  indi:
    mode: disabled
    host: 127.0.0.1
    port: 7624
    drivers: []
    restart:
      initial-backoff-ms: 500
      max-backoff-ms: 30000
```

(`disabled` means neither supervise nor connect — matches Plan A tests that don't want an INDI socket.)

- [ ] **Step 1.6: Update `config.example.yaml`**

Append to `src/main/resources/config.example.yaml`:

```yaml
# INDI driver backplane. v0.1 uses INDI under the hood; users never see it.
indi:
  # managed  = NOCS spawns indiserver with the drivers below
  # external = NOCS connects to an already-running indiserver on host:port
  # disabled = do not connect (headless NOCS, no devices)
  mode: managed
  host: 127.0.0.1
  port: 7624
  drivers:
    - indi_simulator_telescope
    - indi_simulator_ccd
    - indi_simulator_focus
    - indi_simulator_wheel
  restart:
    initial-backoff-ms: 500
    max-backoff-ms: 30000
```

- [ ] **Step 1.7: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.indi.IndiConfigTest'`
Expected: `IndiConfigTest.bindsIndiSection` passes.

Also run: `./gradlew test`
Expected: all prior Plan A tests still green.

- [ ] **Step 1.8: Commit**

```bash
git add src/main/java/dev/nocs/indi/IndiConfig.java \
        src/main/java/dev/nocs/config/NocsProperties.java \
        src/main/resources/application.yaml \
        src/main/resources/config.example.yaml \
        src/test/java/dev/nocs/indi/IndiConfigTest.java
git commit -m "feat: add nocs.indi configuration section"
```

---

### Task 2: INDI XML codec — property model + parser + serialiser

**Files:**
- Create: `src/main/java/dev/nocs/indi/IndiProperty.java`
- Create: `src/main/java/dev/nocs/indi/PropertyUpdate.java`
- Create: `src/main/java/dev/nocs/indi/IndiXmlCodec.java`
- Create: `src/test/resources/indi/fixtures/defSwitchVector.xml`
- Create: `src/test/resources/indi/fixtures/defNumberVector.xml`
- Create: `src/test/resources/indi/fixtures/defBlobVector.xml`
- Create: `src/test/resources/indi/fixtures/setNumberVector.xml`
- Create: `src/test/resources/indi/fixtures/setBlobVector.xml`
- Create: `src/test/java/dev/nocs/indi/IndiXmlCodecTest.java`

Background: INDI messages are concatenated XML fragments (no single root). A top-level fragment is one of:
`getProperties`, `defSwitchVector`, `defNumberVector`, `defTextVector`, `defLightVector`, `defBLOBVector`, `setSwitchVector`, `setNumberVector`, `setTextVector`, `setLightVector`, `setBLOBVector`, `newSwitchVector`, `newNumberVector`, `newTextVector`, `message`, `delProperty`, `enableBLOB`. v0.1 only produces `getProperties`, `enableBLOB`, `newSwitchVector`, `newNumberVector`, `newTextVector`, and only consumes `def*Vector`, `set*Vector`, `message`, `delProperty` (and ignores `Light` variants).

- [ ] **Step 2.1: Create fixtures**

`src/test/resources/indi/fixtures/defSwitchVector.xml`:

```xml
<defSwitchVector device="Telescope Simulator" name="CONNECTION" label="Connection" group="Main" state="Idle" perm="rw" rule="OneOfMany" timeout="60" timestamp="2026-04-22T10:00:00">
    <defSwitch name="CONNECT" label="Connect">Off</defSwitch>
    <defSwitch name="DISCONNECT" label="Disconnect">On</defSwitch>
</defSwitchVector>
```

`src/test/resources/indi/fixtures/defNumberVector.xml`:

```xml
<defNumberVector device="CCD Simulator" name="CCD_EXPOSURE" label="Expose" group="Main" state="Idle" perm="rw" timeout="60" timestamp="2026-04-22T10:00:00">
    <defNumber name="CCD_EXPOSURE_VALUE" label="Duration (s)" format="%g" min="0" max="3600" step="0.1">0</defNumber>
</defNumberVector>
```

`src/test/resources/indi/fixtures/defBlobVector.xml`:

```xml
<defBLOBVector device="CCD Simulator" name="CCD1" label="Image Data" group="Data" state="Idle" perm="ro" timeout="0" timestamp="2026-04-22T10:00:00">
    <defBLOB name="CCD1" label="Image"/>
</defBLOBVector>
```

`src/test/resources/indi/fixtures/setNumberVector.xml`:

```xml
<setNumberVector device="CCD Simulator" name="CCD_EXPOSURE" state="Ok" timestamp="2026-04-22T10:00:05">
    <oneNumber name="CCD_EXPOSURE_VALUE">0</oneNumber>
</setNumberVector>
```

`src/test/resources/indi/fixtures/setBlobVector.xml` (small base64-encoded payload representing the bytes `[0x01, 0x02, 0x03]`):

```xml
<setBLOBVector device="CCD Simulator" name="CCD1" state="Ok" timestamp="2026-04-22T10:00:05">
    <oneBLOB name="CCD1" size="3" format=".fits">AQID</oneBLOB>
</setBLOBVector>
```

- [ ] **Step 2.2: Write the failing codec test**

Create `src/test/java/dev/nocs/indi/IndiXmlCodecTest.java`:

```java
package dev.nocs.indi;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class IndiXmlCodecTest {

    private String fixture(String name) throws Exception {
        try (InputStream in = getClass().getResourceAsStream("/indi/fixtures/" + name)) {
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    @Test
    void parsesDefSwitchVector() throws Exception {
        IndiXmlCodec codec = new IndiXmlCodec();
        List<IndiProperty> props = codec.readAll(fixture("defSwitchVector.xml"));
        assertThat(props).hasSize(1);
        IndiProperty.SwitchVector sw = (IndiProperty.SwitchVector) props.get(0);
        assertThat(sw.device()).isEqualTo("Telescope Simulator");
        assertThat(sw.name()).isEqualTo("CONNECTION");
        assertThat(sw.elements()).containsEntry("CONNECT", false).containsEntry("DISCONNECT", true);
        assertThat(sw.rule()).isEqualTo(IndiProperty.SwitchRule.ONE_OF_MANY);
    }

    @Test
    void parsesDefNumberVector() throws Exception {
        IndiXmlCodec codec = new IndiXmlCodec();
        List<IndiProperty> props = codec.readAll(fixture("defNumberVector.xml"));
        IndiProperty.NumberVector n = (IndiProperty.NumberVector) props.get(0);
        assertThat(n.device()).isEqualTo("CCD Simulator");
        assertThat(n.name()).isEqualTo("CCD_EXPOSURE");
        assertThat(n.elements()).containsEntry("CCD_EXPOSURE_VALUE", 0.0);
    }

    @Test
    void parsesDefBlobVector() throws Exception {
        IndiXmlCodec codec = new IndiXmlCodec();
        List<IndiProperty> props = codec.readAll(fixture("defBlobVector.xml"));
        IndiProperty.BlobVector b = (IndiProperty.BlobVector) props.get(0);
        assertThat(b.name()).isEqualTo("CCD1");
        assertThat(b.bytes()).isNull();
    }

    @Test
    void parsesSetNumberVector() throws Exception {
        IndiXmlCodec codec = new IndiXmlCodec();
        List<IndiProperty> props = codec.readAll(fixture("setNumberVector.xml"));
        IndiProperty.NumberVector n = (IndiProperty.NumberVector) props.get(0);
        assertThat(n.state()).isEqualTo(IndiProperty.State.OK);
        assertThat(n.elements()).containsEntry("CCD_EXPOSURE_VALUE", 0.0);
    }

    @Test
    void parsesSetBlobVector() throws Exception {
        IndiXmlCodec codec = new IndiXmlCodec();
        List<IndiProperty> props = codec.readAll(fixture("setBlobVector.xml"));
        IndiProperty.BlobVector b = (IndiProperty.BlobVector) props.get(0);
        assertThat(b.bytes()).containsExactly(0x01, 0x02, 0x03);
        assertThat(b.format()).isEqualTo(".fits");
    }

    @Test
    void parsesConcatenatedFragments() throws Exception {
        IndiXmlCodec codec = new IndiXmlCodec();
        String concat = fixture("defSwitchVector.xml") + "\n" + fixture("defNumberVector.xml");
        List<IndiProperty> props = codec.readAll(concat);
        assertThat(props).hasSize(2);
    }

    @Test
    void parsesStreamIncrementally() throws Exception {
        IndiXmlCodec codec = new IndiXmlCodec();
        byte[] bytes = (fixture("defSwitchVector.xml") + fixture("defNumberVector.xml"))
                .getBytes(StandardCharsets.UTF_8);
        try (var in = new ByteArrayInputStream(bytes)) {
            List<IndiProperty> out = new java.util.ArrayList<>();
            codec.readStream(in, out::add);
            assertThat(out).hasSize(2);
        }
    }

    @Test
    void writesNewSwitchVector() throws Exception {
        IndiXmlCodec codec = new IndiXmlCodec();
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        codec.writeNewSwitchVector(out, "Telescope Simulator", "CONNECTION",
                Map.of("CONNECT", true, "DISCONNECT", false));
        String xml = out.toString(StandardCharsets.UTF_8);
        assertThat(xml)
                .contains("<newSwitchVector")
                .contains("device=\"Telescope Simulator\"")
                .contains("name=\"CONNECTION\"")
                .contains("<oneSwitch name=\"CONNECT\">On</oneSwitch>")
                .contains("<oneSwitch name=\"DISCONNECT\">Off</oneSwitch>");
    }

    @Test
    void writesNewNumberVector() throws Exception {
        IndiXmlCodec codec = new IndiXmlCodec();
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        codec.writeNewNumberVector(out, "CCD Simulator", "CCD_EXPOSURE",
                Map.of("CCD_EXPOSURE_VALUE", 5.0));
        String xml = out.toString(StandardCharsets.UTF_8);
        assertThat(xml)
                .contains("<newNumberVector")
                .contains("<oneNumber name=\"CCD_EXPOSURE_VALUE\">5.0</oneNumber>");
    }

    @Test
    void writesGetPropertiesAndEnableBlob() throws Exception {
        IndiXmlCodec codec = new IndiXmlCodec();
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        codec.writeGetProperties(out, null, null);
        assertThat(out.toString(StandardCharsets.UTF_8))
                .contains("<getProperties version=\"1.7\"/>");

        out.reset();
        codec.writeEnableBlob(out, "CCD Simulator", "Also");
        assertThat(out.toString(StandardCharsets.UTF_8))
                .contains("<enableBLOB device=\"CCD Simulator\">Also</enableBLOB>");
    }
}
```

- [ ] **Step 2.3: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.indi.IndiXmlCodecTest'`
Expected: compilation errors (classes missing).

- [ ] **Step 2.4: Implement `IndiProperty`**

Create `src/main/java/dev/nocs/indi/IndiProperty.java`:

```java
package dev.nocs.indi;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

public sealed interface IndiProperty
        permits IndiProperty.SwitchVector,
                IndiProperty.NumberVector,
                IndiProperty.TextVector,
                IndiProperty.BlobVector {

    String device();
    String name();
    State state();
    Instant timestamp();

    enum State { IDLE, OK, BUSY, ALERT;
        public static State parse(String s) {
            if (s == null) return IDLE;
            return switch (s) {
                case "Ok" -> OK;
                case "Busy" -> BUSY;
                case "Alert" -> ALERT;
                default -> IDLE;
            };
        }
    }

    enum SwitchRule { ONE_OF_MANY, AT_MOST_ONE, ANY_OF_MANY;
        public static SwitchRule parse(String s) {
            if (s == null) return ONE_OF_MANY;
            return switch (s) {
                case "AtMostOne" -> AT_MOST_ONE;
                case "AnyOfMany" -> ANY_OF_MANY;
                default -> ONE_OF_MANY;
            };
        }
    }

    record SwitchVector(
            String device, String name, State state, Instant timestamp,
            SwitchRule rule, Map<String, Boolean> elements) implements IndiProperty {
        public SwitchVector { elements = elements == null ? Map.of() : Map.copyOf(elements); }
    }

    record NumberVector(
            String device, String name, State state, Instant timestamp,
            Map<String, Double> elements) implements IndiProperty {
        public NumberVector { elements = elements == null ? Map.of() : Map.copyOf(elements); }
    }

    record TextVector(
            String device, String name, State state, Instant timestamp,
            Map<String, String> elements) implements IndiProperty {
        public TextVector { elements = elements == null ? Map.of() : Map.copyOf(elements); }
    }

    record BlobVector(
            String device, String name, State state, Instant timestamp,
            String format, byte[] bytes) implements IndiProperty {}

    static Map<String, String> linked() { return new LinkedHashMap<>(); }
}
```

- [ ] **Step 2.5: Implement `PropertyUpdate`**

Create `src/main/java/dev/nocs/indi/PropertyUpdate.java`:

```java
package dev.nocs.indi;

public record PropertyUpdate(Kind kind, IndiProperty property) {
    public enum Kind { DEFINED, SET, DELETED }
}
```

- [ ] **Step 2.6: Implement `IndiXmlCodec`**

Create `src/main/java/dev/nocs/indi/IndiXmlCodec.java`:

```java
package dev.nocs.indi;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.Writer;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.function.Consumer;
import javax.xml.stream.XMLInputFactory;
import javax.xml.stream.XMLStreamConstants;
import javax.xml.stream.XMLStreamException;
import javax.xml.stream.XMLStreamReader;

/**
 * Minimal INDI XML codec. INDI uses concatenated XML fragments (no single root),
 * so we wrap input in a synthetic root to keep the StAX reader happy.
 */
public final class IndiXmlCodec {

    private static final XMLInputFactory INPUT_FACTORY = XMLInputFactory.newInstance();

    static {
        INPUT_FACTORY.setProperty(XMLInputFactory.IS_NAMESPACE_AWARE, Boolean.FALSE);
        INPUT_FACTORY.setProperty(XMLInputFactory.SUPPORT_DTD, Boolean.FALSE);
        INPUT_FACTORY.setProperty("javax.xml.stream.isSupportingExternalEntities", Boolean.FALSE);
    }

    public List<IndiProperty> readAll(String concatenatedXml) throws IOException {
        List<IndiProperty> out = new ArrayList<>();
        readStream(new ByteArrayInputStream(
                ("<root>" + concatenatedXml + "</root>").getBytes(StandardCharsets.UTF_8)),
                out::add);
        return out;
    }

    /** Reads fragments from a live stream (wrapping in a synthetic root). */
    public void readStream(InputStream wrappedInput, Consumer<IndiProperty> sink) throws IOException {
        try {
            XMLStreamReader r = INPUT_FACTORY.createXMLStreamReader(wrappedInput, "UTF-8");
            while (r.hasNext()) {
                int event = r.next();
                if (event != XMLStreamConstants.START_ELEMENT) continue;
                if ("root".equals(r.getLocalName())) continue;
                IndiProperty p = readFragment(r);
                if (p != null) sink.accept(p);
            }
        } catch (XMLStreamException e) {
            throw new IOException("INDI XML parse error", e);
        }
    }

    private IndiProperty readFragment(XMLStreamReader r) throws XMLStreamException {
        String element = r.getLocalName();
        String device = r.getAttributeValue(null, "device");
        String name = r.getAttributeValue(null, "name");
        String stateAttr = r.getAttributeValue(null, "state");
        IndiProperty.State state = IndiProperty.State.parse(stateAttr);
        Instant ts = parseTs(r.getAttributeValue(null, "timestamp"));

        switch (element) {
            case "defSwitchVector", "setSwitchVector", "newSwitchVector": {
                IndiProperty.SwitchRule rule = IndiProperty.SwitchRule.parse(r.getAttributeValue(null, "rule"));
                Map<String, Boolean> elements = new LinkedHashMap<>();
                while (r.hasNext()) {
                    int ev = r.next();
                    if (ev == XMLStreamConstants.START_ELEMENT &&
                            (r.getLocalName().equals("defSwitch") || r.getLocalName().equals("oneSwitch"))) {
                        String en = r.getAttributeValue(null, "name");
                        String text = r.getElementText().trim();
                        elements.put(en, "On".equalsIgnoreCase(text));
                    } else if (ev == XMLStreamConstants.END_ELEMENT && r.getLocalName().equals(element)) {
                        break;
                    }
                }
                return new IndiProperty.SwitchVector(device, name, state, ts, rule, elements);
            }
            case "defNumberVector", "setNumberVector", "newNumberVector": {
                Map<String, Double> elements = new LinkedHashMap<>();
                while (r.hasNext()) {
                    int ev = r.next();
                    if (ev == XMLStreamConstants.START_ELEMENT &&
                            (r.getLocalName().equals("defNumber") || r.getLocalName().equals("oneNumber"))) {
                        String en = r.getAttributeValue(null, "name");
                        String text = r.getElementText().trim();
                        elements.put(en, parseDouble(text));
                    } else if (ev == XMLStreamConstants.END_ELEMENT && r.getLocalName().equals(element)) {
                        break;
                    }
                }
                return new IndiProperty.NumberVector(device, name, state, ts, elements);
            }
            case "defTextVector", "setTextVector", "newTextVector": {
                Map<String, String> elements = new LinkedHashMap<>();
                while (r.hasNext()) {
                    int ev = r.next();
                    if (ev == XMLStreamConstants.START_ELEMENT &&
                            (r.getLocalName().equals("defText") || r.getLocalName().equals("oneText"))) {
                        String en = r.getAttributeValue(null, "name");
                        String text = r.getElementText();
                        elements.put(en, text == null ? "" : text);
                    } else if (ev == XMLStreamConstants.END_ELEMENT && r.getLocalName().equals(element)) {
                        break;
                    }
                }
                return new IndiProperty.TextVector(device, name, state, ts, elements);
            }
            case "defBLOBVector": {
                skipToClose(r, element);
                return new IndiProperty.BlobVector(device, name, state, ts, null, null);
            }
            case "setBLOBVector": {
                String format = null;
                byte[] bytes = null;
                while (r.hasNext()) {
                    int ev = r.next();
                    if (ev == XMLStreamConstants.START_ELEMENT && r.getLocalName().equals("oneBLOB")) {
                        format = r.getAttributeValue(null, "format");
                        String base64 = r.getElementText();
                        bytes = Base64.getMimeDecoder().decode(base64.replaceAll("\\s", ""));
                    } else if (ev == XMLStreamConstants.END_ELEMENT && r.getLocalName().equals(element)) {
                        break;
                    }
                }
                return new IndiProperty.BlobVector(device, name, state, ts, format, bytes);
            }
            default: {
                skipToClose(r, element);
                return null;
            }
        }
    }

    private void skipToClose(XMLStreamReader r, String name) throws XMLStreamException {
        int depth = 1;
        while (r.hasNext() && depth > 0) {
            int ev = r.next();
            if (ev == XMLStreamConstants.START_ELEMENT) depth++;
            else if (ev == XMLStreamConstants.END_ELEMENT) depth--;
        }
    }

    private static double parseDouble(String text) {
        if (text == null || text.isBlank()) return 0.0;
        try { return Double.parseDouble(text); }
        catch (NumberFormatException e) { return 0.0; }
    }

    private static Instant parseTs(String ts) {
        if (ts == null || ts.isBlank()) return Instant.now();
        try { return Instant.parse(ts.endsWith("Z") ? ts : ts + "Z"); }
        catch (Exception e) { return Instant.now(); }
    }

    // ─── Serialisation ──────────────────────────────────────────────────

    public void writeGetProperties(OutputStream out, String device, String property) throws IOException {
        Writer w = writer(out);
        w.write("<getProperties version=\"1.7\"");
        if (device != null) w.write(" device=\"" + escape(device) + "\"");
        if (property != null) w.write(" name=\"" + escape(property) + "\"");
        w.write("/>\n");
        w.flush();
    }

    public void writeEnableBlob(OutputStream out, String device, String mode) throws IOException {
        Writer w = writer(out);
        w.write("<enableBLOB device=\"" + escape(device) + "\">" + mode + "</enableBLOB>\n");
        w.flush();
    }

    public void writeNewSwitchVector(OutputStream out, String device, String name,
                                     Map<String, Boolean> elements) throws IOException {
        Writer w = writer(out);
        w.write("<newSwitchVector device=\"" + escape(device) + "\" name=\"" + escape(name) + "\">\n");
        for (var e : elements.entrySet()) {
            w.write("  <oneSwitch name=\"" + escape(e.getKey()) + "\">" + (e.getValue() ? "On" : "Off") + "</oneSwitch>\n");
        }
        w.write("</newSwitchVector>\n");
        w.flush();
    }

    public void writeNewNumberVector(OutputStream out, String device, String name,
                                     Map<String, Double> elements) throws IOException {
        Writer w = writer(out);
        w.write("<newNumberVector device=\"" + escape(device) + "\" name=\"" + escape(name) + "\">\n");
        for (var e : elements.entrySet()) {
            w.write("  <oneNumber name=\"" + escape(e.getKey()) + "\">"
                    + String.format(Locale.ROOT, "%s", e.getValue()) + "</oneNumber>\n");
        }
        w.write("</newNumberVector>\n");
        w.flush();
    }

    public void writeNewTextVector(OutputStream out, String device, String name,
                                   Map<String, String> elements) throws IOException {
        Writer w = writer(out);
        w.write("<newTextVector device=\"" + escape(device) + "\" name=\"" + escape(name) + "\">\n");
        for (var e : elements.entrySet()) {
            w.write("  <oneText name=\"" + escape(e.getKey()) + "\">" + escape(e.getValue()) + "</oneText>\n");
        }
        w.write("</newTextVector>\n");
        w.flush();
    }

    private Writer writer(OutputStream out) {
        return new OutputStreamWriter(out, StandardCharsets.UTF_8);
    }

    private static String escape(String s) {
        if (s == null) return "";
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;");
    }
}
```

- [ ] **Step 2.7: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.indi.IndiXmlCodecTest'`
Expected: all nine tests pass.

- [ ] **Step 2.8: Commit**

```bash
git add src/main/java/dev/nocs/indi/IndiProperty.java \
        src/main/java/dev/nocs/indi/PropertyUpdate.java \
        src/main/java/dev/nocs/indi/IndiXmlCodec.java \
        src/test/java/dev/nocs/indi/IndiXmlCodecTest.java \
        src/test/resources/indi/fixtures/
git commit -m "feat: minimal INDI XML codec (parse + serialise switch/number/text/BLOB)"
```

---

### Task 3: INDI TCP client — lifecycle, read loop, property registry

**Files:**
- Create: `src/main/java/dev/nocs/indi/IndiClient.java`
- Create: `src/test/java/dev/nocs/indi/FakeIndiServer.java` (test helper)
- Create: `src/test/java/dev/nocs/indi/IndiClientTest.java`
- Modify: `build.gradle.kts` (add `org.awaitility:awaitility` test dep)

- [ ] **Step 3.1: Add Awaitility**

Append to the `dependencies { ... }` block in `build.gradle.kts`:

```kotlin
testImplementation("org.awaitility:awaitility:4.2.2")
```

Run: `./gradlew dependencies --configuration testRuntimeClasspath | grep awaitility` and confirm it resolves.

- [ ] **Step 3.2: Create the fake server test helper**

Create `src/test/java/dev/nocs/indi/FakeIndiServer.java`:

```java
package dev.nocs.indi;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicReference;

/** Minimal in-process INDI-ish server used only by IndiClientTest. */
public final class FakeIndiServer implements AutoCloseable {

    private final ServerSocket server;
    private final Thread acceptor;
    private final AtomicReference<Socket> client = new AtomicReference<>();
    private final List<String> received = new CopyOnWriteArrayList<>();
    private final CountDownLatch connected = new CountDownLatch(1);

    public FakeIndiServer() throws IOException {
        this.server = new ServerSocket(0, 50, InetAddress.getLoopbackAddress());
        this.acceptor = new Thread(this::accept, "fake-indi-acceptor");
        this.acceptor.setDaemon(true);
        this.acceptor.start();
    }

    public int port() { return server.getLocalPort(); }

    public List<String> receivedMessages() { return new ArrayList<>(received); }

    public void awaitConnected() throws InterruptedException { connected.await(); }

    public void send(String xml) throws IOException {
        Socket s = client.get();
        if (s == null) throw new IOException("no client connected");
        OutputStream out = s.getOutputStream();
        out.write(xml.getBytes(StandardCharsets.UTF_8));
        out.flush();
    }

    private void accept() {
        try (Socket sock = server.accept()) {
            client.set(sock);
            connected.countDown();
            BufferedReader br = new BufferedReader(new InputStreamReader(sock.getInputStream(), StandardCharsets.UTF_8));
            StringBuilder buf = new StringBuilder();
            char[] cbuf = new char[1024];
            int n;
            while ((n = br.read(cbuf)) != -1) {
                buf.append(cbuf, 0, n);
                flushMessages(buf);
            }
        } catch (IOException ignored) { }
    }

    private void flushMessages(StringBuilder buf) {
        int depth = 0;
        int start = -1;
        for (int i = 0; i < buf.length(); i++) {
            char c = buf.charAt(i);
            if (c == '<') {
                if (i + 1 < buf.length() && buf.charAt(i + 1) == '/') {
                    depth--;
                    if (depth == 0 && start >= 0) {
                        int end = buf.indexOf(">", i) + 1;
                        if (end <= 0) return;
                        received.add(buf.substring(start, end));
                        buf.delete(0, end);
                        i = -1;
                        start = -1;
                    }
                } else if (buf.indexOf("/>", i) >= 0
                        && buf.indexOf("/>", i) < buf.indexOf(">", i + 1) + 1
                        && depth == 0) {
                    int end = buf.indexOf("/>", i) + 2;
                    received.add(buf.substring(i, end));
                    buf.delete(0, end);
                    i = -1;
                    start = -1;
                } else {
                    if (depth == 0) start = i;
                    depth++;
                }
            }
        }
    }

    @Override
    public void close() throws IOException {
        try { if (client.get() != null) client.get().close(); } catch (IOException ignored) {}
        server.close();
    }
}
```

(Simple "count angle brackets" parser — good enough for the few messages the client sends in tests.)

- [ ] **Step 3.3: Write the failing client test**

Create `src/test/java/dev/nocs/indi/IndiClientTest.java`:

```java
package dev.nocs.indi;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class IndiClientTest {

    @Test
    void connectsAndSendsGetProperties() throws Exception {
        try (FakeIndiServer server = new FakeIndiServer();
             IndiClient client = new IndiClient()) {

            client.connect("127.0.0.1", server.port());
            server.awaitConnected();

            Awaitility.await().atMost(Duration.ofSeconds(2)).untilAsserted(() ->
                    assertThat(server.receivedMessages())
                            .anyMatch(s -> s.contains("<getProperties")));
        }
    }

    @Test
    void receivesDefinesAndBuildsRegistry() throws Exception {
        try (FakeIndiServer server = new FakeIndiServer();
             IndiClient client = new IndiClient()) {

            client.connect("127.0.0.1", server.port());
            server.awaitConnected();

            server.send("""
                <defSwitchVector device="Telescope Simulator" name="CONNECTION" state="Idle" rule="OneOfMany">
                    <defSwitch name="CONNECT">Off</defSwitch>
                    <defSwitch name="DISCONNECT">On</defSwitch>
                </defSwitchVector>
                """);

            Awaitility.await().atMost(Duration.ofSeconds(2)).untilAsserted(() ->
                    assertThat(client.properties("Telescope Simulator"))
                            .anyMatch(p -> p.name().equals("CONNECTION")));
        }
    }

    @Test
    void publishesUpdatesToSubscribers() throws Exception {
        try (FakeIndiServer server = new FakeIndiServer();
             IndiClient client = new IndiClient()) {

            List<PropertyUpdate> seen = new CopyOnWriteArrayList<>();
            var sub = client.updates().subscribe(seen::add);

            client.connect("127.0.0.1", server.port());
            server.awaitConnected();

            server.send("""
                <defNumberVector device="CCD Simulator" name="CCD_EXPOSURE" state="Idle">
                    <defNumber name="CCD_EXPOSURE_VALUE">0</defNumber>
                </defNumberVector>
                """);
            server.send("""
                <setNumberVector device="CCD Simulator" name="CCD_EXPOSURE" state="Busy">
                    <oneNumber name="CCD_EXPOSURE_VALUE">5</oneNumber>
                </setNumberVector>
                """);

            Awaitility.await().atMost(Duration.ofSeconds(2)).untilAsserted(() -> {
                assertThat(seen).hasSizeGreaterThanOrEqualTo(2);
                assertThat(seen.get(0).kind()).isEqualTo(PropertyUpdate.Kind.DEFINED);
                assertThat(seen.get(1).kind()).isEqualTo(PropertyUpdate.Kind.SET);
            });
            sub.dispose();
        }
    }

    @Test
    void listsDiscoveredDevices() throws Exception {
        try (FakeIndiServer server = new FakeIndiServer();
             IndiClient client = new IndiClient()) {
            client.connect("127.0.0.1", server.port());
            server.awaitConnected();

            server.send("<defSwitchVector device=\"Telescope Simulator\" name=\"CONNECTION\" state=\"Idle\"><defSwitch name=\"CONNECT\">Off</defSwitch><defSwitch name=\"DISCONNECT\">On</defSwitch></defSwitchVector>\n");
            server.send("<defNumberVector device=\"CCD Simulator\" name=\"CCD_EXPOSURE\" state=\"Idle\"><defNumber name=\"CCD_EXPOSURE_VALUE\">0</defNumber></defNumberVector>\n");

            Awaitility.await().atMost(Duration.ofSeconds(2)).untilAsserted(() ->
                    assertThat(new ArrayList<>(client.devices()))
                            .contains("Telescope Simulator", "CCD Simulator"));
        }
    }
}
```

- [ ] **Step 3.4: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.indi.IndiClientTest'`
Expected: compilation failures (no `IndiClient`).

- [ ] **Step 3.5: Implement `IndiClient`**

Create `src/main/java/dev/nocs/indi/IndiClient.java`:

```java
package dev.nocs.indi;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Sinks;

public class IndiClient implements AutoCloseable {

    private static final Logger log = LoggerFactory.getLogger(IndiClient.class);

    private final IndiXmlCodec codec = new IndiXmlCodec();
    private final Map<String, Map<String, IndiProperty>> registry = new ConcurrentHashMap<>();
    private final Sinks.Many<PropertyUpdate> sink = Sinks.many().multicast().onBackpressureBuffer(2048, false);
    private final AtomicBoolean running = new AtomicBoolean(false);

    private volatile Socket socket;
    private volatile OutputStream out;
    private volatile Thread reader;

    public void connect(String host, int port) throws IOException {
        close();
        Socket s = new Socket();
        s.connect(new InetSocketAddress(host, port), 5000);
        s.setTcpNoDelay(true);
        this.socket = s;
        this.out = s.getOutputStream();
        running.set(true);
        this.reader = Thread.ofVirtual().name("indi-reader").start(this::readLoop);
        codec.writeGetProperties(out, null, null);
    }

    private void readLoop() {
        try (InputStream wrapped = prependRoot(socket.getInputStream())) {
            codec.readStream(wrapped, this::onProperty);
        } catch (IOException e) {
            if (running.get()) log.warn("INDI read loop ended: {}", e.toString());
        } finally {
            running.set(false);
        }
    }

    /** Wraps the live socket stream in "<root>…</root>" so StAX sees a single document. */
    private static InputStream prependRoot(InputStream in) {
        byte[] prefix = "<root>".getBytes();
        return new java.io.SequenceInputStream(
                new java.io.ByteArrayInputStream(prefix),
                in);
    }

    private void onProperty(IndiProperty p) {
        PropertyUpdate.Kind kind = registry
                .computeIfAbsent(p.device(), k -> new ConcurrentHashMap<>())
                .put(p.name(), p) == null ? PropertyUpdate.Kind.DEFINED : PropertyUpdate.Kind.SET;
        sink.tryEmitNext(new PropertyUpdate(kind, p));
    }

    public Flux<PropertyUpdate> updates() { return sink.asFlux(); }

    public Collection<IndiProperty> properties(String device) {
        Map<String, IndiProperty> m = registry.get(device);
        return m == null ? List.of() : m.values();
    }

    public IndiProperty property(String device, String name) {
        Map<String, IndiProperty> m = registry.get(device);
        return m == null ? null : m.get(name);
    }

    public Set<String> devices() { return registry.keySet(); }

    public synchronized void setSwitch(String device, String name, Map<String, Boolean> elements) throws IOException {
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        codec.writeNewSwitchVector(buf, device, name, elements);
        out.write(buf.toByteArray());
        out.flush();
    }

    public synchronized void setNumber(String device, String name, Map<String, Double> elements) throws IOException {
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        codec.writeNewNumberVector(buf, device, name, elements);
        out.write(buf.toByteArray());
        out.flush();
    }

    public synchronized void setText(String device, String name, Map<String, String> elements) throws IOException {
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        codec.writeNewTextVector(buf, device, name, elements);
        out.write(buf.toByteArray());
        out.flush();
    }

    public synchronized void enableBlob(String device, String mode) throws IOException {
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        codec.writeEnableBlob(buf, device, mode);
        out.write(buf.toByteArray());
        out.flush();
    }

    public boolean isConnected() { return running.get() && socket != null && !socket.isClosed(); }

    @Override
    public synchronized void close() {
        if (!running.compareAndSet(true, false)) {
            try { if (socket != null) socket.close(); } catch (IOException ignored) {}
            return;
        }
        try { if (socket != null) socket.close(); } catch (IOException ignored) {}
        if (reader != null) {
            try { reader.join(1000); } catch (InterruptedException ignored) { Thread.currentThread().interrupt(); }
        }
    }
}
```

- [ ] **Step 3.6: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.indi.IndiClientTest'`
Expected: four tests pass.

- [ ] **Step 3.7: Commit**

```bash
git add src/main/java/dev/nocs/indi/IndiClient.java \
        src/test/java/dev/nocs/indi/FakeIndiServer.java \
        src/test/java/dev/nocs/indi/IndiClientTest.java \
        build.gradle.kts
git commit -m "feat: in-process INDI client with property registry and Reactor updates"
```

---

### Task 4: INDI client BLOB reception

**Files:**
- Modify: `src/main/java/dev/nocs/indi/IndiClient.java` (add `onBlob` callback)
- Modify: `src/test/java/dev/nocs/indi/IndiClientTest.java` (add BLOB test)

- [ ] **Step 4.1: Extend the test with a BLOB case**

Append to `IndiClientTest`:

```java
    @Test
    void receivesBlob() throws Exception {
        try (FakeIndiServer server = new FakeIndiServer();
             IndiClient client = new IndiClient()) {

            java.util.List<byte[]> blobs = new java.util.concurrent.CopyOnWriteArrayList<>();
            client.onBlob((device, propertyName, format, bytes) -> blobs.add(bytes));

            client.connect("127.0.0.1", server.port());
            server.awaitConnected();

            client.enableBlob("CCD Simulator", "Also");

            server.send("<setBLOBVector device=\"CCD Simulator\" name=\"CCD1\" state=\"Ok\">" +
                       "<oneBLOB name=\"CCD1\" size=\"3\" format=\".fits\">AQID</oneBLOB>" +
                       "</setBLOBVector>\n");

            org.awaitility.Awaitility.await().atMost(java.time.Duration.ofSeconds(2)).untilAsserted(() ->
                    assertThat(blobs).hasSize(1).first().extracting(Object::toString).isNotNull());
            assertThat(blobs.get(0)).containsExactly(1, 2, 3);
        }
    }
```

- [ ] **Step 4.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.indi.IndiClientTest.receivesBlob'`
Expected: `onBlob` does not exist.

- [ ] **Step 4.3: Add BLOB callback to `IndiClient`**

Add near the top of `IndiClient`:

```java
    @FunctionalInterface
    public interface BlobCallback {
        void accept(String device, String propertyName, String format, byte[] bytes);
    }

    private volatile BlobCallback blobCallback = (d, n, f, b) -> {};

    public void onBlob(BlobCallback cb) { this.blobCallback = cb == null ? (d, n, f, b) -> {} : cb; }
```

Replace `onProperty` with:

```java
    private void onProperty(IndiProperty p) {
        PropertyUpdate.Kind kind;
        if (p instanceof IndiProperty.BlobVector blob && blob.bytes() != null) {
            kind = PropertyUpdate.Kind.SET;
            try {
                blobCallback.accept(blob.device(), blob.name(), blob.format(), blob.bytes());
            } catch (RuntimeException e) {
                log.warn("BLOB callback failed for {}/{}", blob.device(), blob.name(), e);
            }
        } else {
            kind = registry
                    .computeIfAbsent(p.device(), k -> new ConcurrentHashMap<>())
                    .put(p.name(), p) == null ? PropertyUpdate.Kind.DEFINED : PropertyUpdate.Kind.SET;
        }
        sink.tryEmitNext(new PropertyUpdate(kind, p));
    }
```

- [ ] **Step 4.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.indi.IndiClientTest'`
Expected: all five tests (including `receivesBlob`) pass.

- [ ] **Step 4.5: Commit**

```bash
git add src/main/java/dev/nocs/indi/IndiClient.java \
        src/test/java/dev/nocs/indi/IndiClientTest.java
git commit -m "feat: IndiClient BLOB callback for CCD image delivery"
```

---

### Task 5: `indiserver` process supervisor

**Files:**
- Create: `src/main/java/dev/nocs/indi/IndiServerSupervisor.java`
- Create: `src/test/java/dev/nocs/indi/IndiServerSupervisorTest.java`

Contract: on start, spawn `indiserver -p <port> [drivers…]` (or not, if no drivers). On process exit with a non-zero code while the supervisor is still in the `STARTED` state, wait `min(initialBackoff * 2^failures, maxBackoff)` and respawn. On `stop()`, send SIGTERM and wait up to 5 s, then SIGKILL. Pipe stdout/stderr into SLF4J at INFO/WARN. Emit `Event.of(SYSTEM, "indiserver.up" | "indiserver.down" | "indiserver.respawn", …)` on the bus.

The unit test uses a tiny shell script (`/bin/sh -c 'exit 1'`) as a stand-in; we do **not** require `indiserver` for this task's test. Task 13's integration test uses the real binary.

- [ ] **Step 5.1: Write the failing supervisor test**

Create `src/test/java/dev/nocs/indi/IndiServerSupervisorTest.java`:

```java
package dev.nocs.indi;

import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.DisabledOnOs;
import org.junit.jupiter.api.condition.OS;

import static org.assertj.core.api.Assertions.assertThat;

@DisabledOnOs(OS.WINDOWS)
class IndiServerSupervisorTest {

    @Test
    void respawnsAfterFailureWithBackoff() throws Exception {
        EventBus bus = new EventBus();
        CopyOnWriteArrayList<String> events = new CopyOnWriteArrayList<>();
        var sub = bus.subscribe(java.util.EnumSet.of(Topic.SYSTEM))
                .subscribe(e -> events.add((String) e.type()));

        IndiConfig cfg = new IndiConfig(
                IndiConfig.Mode.MANAGED, "127.0.0.1", 7624,
                List.of("true-stub-that-exits-1"),
                new IndiConfig.Restart(50L, 500L));

        IndiServerSupervisor sup = new IndiServerSupervisor(cfg, bus) {
            @Override
            protected ProcessBuilder buildProcess() {
                return new ProcessBuilder("/bin/sh", "-c", "echo starting; exit 1");
            }
        };

        sup.start();

        Awaitility.await().atMost(Duration.ofSeconds(4)).untilAsserted(() ->
                assertThat(events).filteredOn(e -> e.equals("indiserver.down")).hasSizeGreaterThanOrEqualTo(2));

        sup.stop();
        sub.dispose();
    }

    @Test
    void stopTerminatesRunningProcess() throws Exception {
        EventBus bus = new EventBus();
        IndiConfig cfg = new IndiConfig(
                IndiConfig.Mode.MANAGED, "127.0.0.1", 7624,
                List.of("sleep-stub"),
                new IndiConfig.Restart(500L, 2000L));

        IndiServerSupervisor sup = new IndiServerSupervisor(cfg, bus) {
            @Override
            protected ProcessBuilder buildProcess() {
                return new ProcessBuilder("/bin/sh", "-c", "trap 'exit 0' TERM; while :; do sleep 0.1; done");
            }
        };

        sup.start();
        Awaitility.await().atMost(Duration.ofSeconds(2)).until(sup::isRunning);
        sup.stop();
        assertThat(sup.isRunning()).isFalse();
    }
}
```

- [ ] **Step 5.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.indi.IndiServerSupervisorTest'`
Expected: class missing.

- [ ] **Step 5.3: Implement `IndiServerSupervisor`**

Create `src/main/java/dev/nocs/indi/IndiServerSupervisor.java`:

```java
package dev.nocs.indi;

import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class IndiServerSupervisor {

    private static final Logger log = LoggerFactory.getLogger(IndiServerSupervisor.class);

    private final IndiConfig config;
    private final EventBus bus;
    private final AtomicBoolean started = new AtomicBoolean(false);

    private volatile Thread loop;
    private volatile Process current;
    private int consecutiveFailures = 0;

    public IndiServerSupervisor(IndiConfig config, EventBus bus) {
        this.config = config;
        this.bus = bus;
    }

    public void start() {
        if (config.mode() != IndiConfig.Mode.MANAGED) {
            log.info("INDI supervisor disabled (mode={})", config.mode());
            return;
        }
        if (!started.compareAndSet(false, true)) return;
        loop = Thread.ofVirtual().name("indi-supervisor").start(this::runLoop);
    }

    public void stop() {
        if (!started.compareAndSet(true, false)) return;
        Process p = current;
        if (p != null && p.isAlive()) {
            p.destroy();
            try {
                if (!p.waitFor(5, java.util.concurrent.TimeUnit.SECONDS)) {
                    p.destroyForcibly();
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                p.destroyForcibly();
            }
        }
        if (loop != null) {
            try { loop.join(2000); } catch (InterruptedException ignored) { Thread.currentThread().interrupt(); }
        }
    }

    public boolean isRunning() {
        Process p = current;
        return started.get() && p != null && p.isAlive();
    }

    protected ProcessBuilder buildProcess() {
        List<String> cmd = new ArrayList<>();
        cmd.add("indiserver");
        cmd.add("-p");
        cmd.add(String.valueOf(config.port()));
        cmd.addAll(config.drivers());
        return new ProcessBuilder(cmd);
    }

    private void runLoop() {
        while (started.get()) {
            try {
                ProcessBuilder pb = buildProcess().redirectErrorStream(true);
                current = pb.start();
                bus.publish(Event.of(Topic.SYSTEM, "indiserver.up",
                        Map.of("pid", (long) current.pid(), "drivers", config.drivers())));
                pipeLogs(current);
                int code = current.waitFor();
                bus.publish(Event.of(Topic.SYSTEM, "indiserver.down",
                        Map.of("exitCode", code)));
                if (!started.get()) break;
                long backoff = Math.min(
                        config.restart().initialBackoffMs() * (long) Math.pow(2, consecutiveFailures),
                        config.restart().maxBackoffMs());
                consecutiveFailures++;
                bus.publish(Event.of(Topic.SYSTEM, "indiserver.respawn",
                        Map.of("backoffMs", backoff, "consecutiveFailures", consecutiveFailures)));
                Thread.sleep(backoff);
            } catch (IOException e) {
                log.warn("indiserver start failed: {}", e.toString());
                try { Thread.sleep(config.restart().initialBackoffMs()); }
                catch (InterruptedException ie) { Thread.currentThread().interrupt(); return; }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return;
            }
        }
    }

    private void pipeLogs(Process p) {
        Thread.ofVirtual().name("indi-log").start(() -> {
            try (BufferedReader r = new BufferedReader(new InputStreamReader(
                    p.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = r.readLine()) != null) {
                    log.info("[indiserver] {}", line);
                }
            } catch (IOException e) {
                log.debug("indiserver log pipe ended: {}", e.toString());
            }
        });
    }
}
```

- [ ] **Step 5.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.indi.IndiServerSupervisorTest'`
Expected: both tests pass within a few seconds.

- [ ] **Step 5.5: Commit**

```bash
git add src/main/java/dev/nocs/indi/IndiServerSupervisor.java \
        src/test/java/dev/nocs/indi/IndiServerSupervisorTest.java
git commit -m "feat: indiserver child-process supervisor with restart backoff"
```

---

### Task 6: Abstract device layer — interfaces, state enums, events

**Files:**
- Create: `src/main/java/dev/nocs/device/DeviceKind.java`
- Create: `src/main/java/dev/nocs/device/DeviceId.java`
- Create: `src/main/java/dev/nocs/device/Device.java`
- Create: `src/main/java/dev/nocs/device/MountState.java`
- Create: `src/main/java/dev/nocs/device/CameraState.java`
- Create: `src/main/java/dev/nocs/device/FilterWheelState.java`
- Create: `src/main/java/dev/nocs/device/FocuserState.java`
- Create: `src/main/java/dev/nocs/device/Mount.java`
- Create: `src/main/java/dev/nocs/device/Camera.java`
- Create: `src/main/java/dev/nocs/device/FilterWheel.java`
- Create: `src/main/java/dev/nocs/device/Focuser.java`
- Create: `src/main/java/dev/nocs/device/DeviceStateChanged.java`
- Create: `src/main/java/dev/nocs/device/CameraImageSink.java`
- Create: `src/test/java/dev/nocs/device/DeviceIdTest.java`

Interfaces only — no implementations yet. TDD applies to `DeviceId.slug(...)`.

- [ ] **Step 6.1: Write the failing `DeviceId` test**

Create `src/test/java/dev/nocs/device/DeviceIdTest.java`:

```java
package dev.nocs.device;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class DeviceIdTest {

    @Test
    void slugifiesIndiName() {
        assertThat(DeviceId.slug("Telescope Simulator").value()).isEqualTo("telescope-simulator");
        assertThat(DeviceId.slug("CCD_Simulator_1").value()).isEqualTo("ccd-simulator-1");
        assertThat(DeviceId.slug(" ZWO ASI294MC Pro ").value()).isEqualTo("zwo-asi294mc-pro");
    }

    @Test
    void rejectsEmpty() {
        assertThat(org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class,
                () -> DeviceId.slug("   ")).getMessage())
                .contains("blank");
    }
}
```

- [ ] **Step 6.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.device.DeviceIdTest'`
Expected: missing class.

- [ ] **Step 6.3: Implement `DeviceKind` and `DeviceId`**

`src/main/java/dev/nocs/device/DeviceKind.java`:

```java
package dev.nocs.device;

public enum DeviceKind { MOUNT, CAMERA, FILTERWHEEL, FOCUSER, UNKNOWN }
```

`src/main/java/dev/nocs/device/DeviceId.java`:

```java
package dev.nocs.device;

public record DeviceId(String value) {

    public DeviceId {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("device id is blank");
        }
    }

    public static DeviceId slug(String indiName) {
        if (indiName == null || indiName.isBlank()) {
            throw new IllegalArgumentException("indi device name is blank");
        }
        String s = indiName.trim().toLowerCase()
                .replaceAll("[^a-z0-9]+", "-")
                .replaceAll("^-|-$", "");
        return new DeviceId(s);
    }
}
```

- [ ] **Step 6.4: State enums**

`src/main/java/dev/nocs/device/MountState.java`:

```java
package dev.nocs.device;

public enum MountState {
    DISCONNECTED, IDLE, SLEWING, TRACKING, PARKING, PARKED, ERROR, E_STOPPED
}
```

`src/main/java/dev/nocs/device/CameraState.java`:

```java
package dev.nocs.device;

public enum CameraState {
    DISCONNECTED, IDLE, COOLING, READY, EXPOSING, DOWNLOADING, ERROR, E_STOPPED
}
```

`src/main/java/dev/nocs/device/FilterWheelState.java`:

```java
package dev.nocs.device;

public enum FilterWheelState {
    DISCONNECTED, IDLE, MOVING, ERROR
}
```

`src/main/java/dev/nocs/device/FocuserState.java`:

```java
package dev.nocs.device;

public enum FocuserState {
    DISCONNECTED, IDLE, MOVING, ERROR
}
```

- [ ] **Step 6.5: `Device` and kind-specific interfaces**

`src/main/java/dev/nocs/device/Device.java`:

```java
package dev.nocs.device;

public interface Device {
    DeviceId id();
    String indiName();
    DeviceKind kind();
    boolean isConnected();
    void connect();
    void disconnect();
}
```

`src/main/java/dev/nocs/device/Mount.java`:

```java
package dev.nocs.device;

public interface Mount extends Device {
    MountState state();
    void slew(double raHours, double decDegrees);
    void syncTo(double raHours, double decDegrees);
    void park();
    void unpark();
    void abort();
    @Override default DeviceKind kind() { return DeviceKind.MOUNT; }
}
```

`src/main/java/dev/nocs/device/Camera.java`:

```java
package dev.nocs.device;

public interface Camera extends Device {
    CameraState state();
    void cool(double setpointCelsius);
    /** Starts an exposure. Returns when the server has accepted the request (not when the image is downloaded). */
    void expose(double durationSeconds);
    void abortExposure();
    Double currentTemperatureCelsius();
    @Override default DeviceKind kind() { return DeviceKind.CAMERA; }
}
```

`src/main/java/dev/nocs/device/FilterWheel.java`:

```java
package dev.nocs.device;

import java.util.List;

public interface FilterWheel extends Device {
    FilterWheelState state();
    List<String> slotNames();
    int currentSlot();
    void selectSlot(int slot);
    @Override default DeviceKind kind() { return DeviceKind.FILTERWHEEL; }
}
```

`src/main/java/dev/nocs/device/Focuser.java`:

```java
package dev.nocs.device;

public interface Focuser extends Device {
    FocuserState state();
    int currentPosition();
    void moveAbsolute(int position);
    void moveRelative(int delta);
    void abort();
    @Override default DeviceKind kind() { return DeviceKind.FOCUSER; }
}
```

- [ ] **Step 6.6: Events**

`src/main/java/dev/nocs/device/DeviceStateChanged.java`:

```java
package dev.nocs.device;

import java.util.Map;

public record DeviceStateChanged(
        DeviceId id, DeviceKind kind, String oldState, String newState) {

    public Map<String, Object> toPayload() {
        return Map.of(
                "id", id.value(),
                "kind", kind.name().toLowerCase(),
                "old", oldState,
                "new", newState);
    }
}
```

`src/main/java/dev/nocs/device/CameraImageSink.java`:

```java
package dev.nocs.device;

public interface CameraImageSink {
    /** Called when a BLOB has been fully received for a camera. Implementations must not block the reader thread. */
    void accept(DeviceId camera, byte[] bytes, String extension);
}
```

- [ ] **Step 6.7: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.device.DeviceIdTest'`
Expected: both tests pass.

Run: `./gradlew compileJava`
Expected: `BUILD SUCCESSFUL` — the new interfaces compile.

- [ ] **Step 6.8: Commit**

```bash
git add src/main/java/dev/nocs/device/ \
        src/test/java/dev/nocs/device/DeviceIdTest.java
git commit -m "feat: abstract device layer (Mount/Camera/FilterWheel/Focuser + state enums)"
```

---

### Task 7: `TempDirCameraImageSink` default implementation

**Files:**
- Create: `src/main/java/dev/nocs/device/TempDirCameraImageSink.java`
- Create: `src/test/java/dev/nocs/device/TempDirCameraImageSinkTest.java`

- [ ] **Step 7.1: Failing test**

`src/test/java/dev/nocs/device/TempDirCameraImageSinkTest.java`:

```java
package dev.nocs.device;

import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.assertj.core.api.Assertions.assertThat;

class TempDirCameraImageSinkTest {

    @Test
    void writesBlobAndPublishesEvent(@TempDir Path tempRoot) throws Exception {
        EventBus bus = new EventBus();
        CopyOnWriteArrayList<Map<String, Object>> seen = new CopyOnWriteArrayList<>();
        var sub = bus.subscribe(java.util.EnumSet.of(Topic.CAMERA))
                .filter(e -> "image_received".equals(e.type()))
                .subscribe(e -> seen.add(e.payload()));

        TempDirCameraImageSink sink = new TempDirCameraImageSink(tempRoot, bus);
        sink.accept(new DeviceId("ccd-simulator"), new byte[]{1, 2, 3, 4}, ".fits");

        Awaitility.await().atMost(Duration.ofSeconds(2)).untilAsserted(() -> {
            assertThat(seen).hasSize(1);
            Path p = Path.of((String) seen.get(0).get("path"));
            assertThat(Files.exists(p)).isTrue();
            assertThat(Files.readAllBytes(p)).containsExactly(1, 2, 3, 4);
            assertThat(p.getParent().getFileName().toString()).isEqualTo("tmp");
        });
        sub.dispose();
    }
}
```

- [ ] **Step 7.2: Implement**

`src/main/java/dev/nocs/device/TempDirCameraImageSink.java`:

```java
package dev.nocs.device;

import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

public class TempDirCameraImageSink implements CameraImageSink {

    private final Path tempRoot;
    private final EventBus bus;
    private final AtomicLong seq = new AtomicLong();

    public TempDirCameraImageSink(Path dataDir, EventBus bus) {
        this.tempRoot = dataDir.resolve("captures").resolve("tmp");
        this.bus = bus;
    }

    @Override
    public void accept(DeviceId camera, byte[] bytes, String extension) {
        try {
            Files.createDirectories(tempRoot);
            String ext = (extension == null || extension.isBlank()) ? ".bin" :
                    (extension.startsWith(".") ? extension : "." + extension);
            Path target = tempRoot.resolve(
                    Instant.now().toEpochMilli() + "-" + seq.incrementAndGet() + ext);
            Files.write(target, bytes);
            bus.publish(Event.of(Topic.CAMERA, "image_received", Map.of(
                    "device", camera.value(),
                    "path", target.toString(),
                    "bytes", bytes.length,
                    "extension", ext)));
        } catch (IOException e) {
            throw new RuntimeException("failed to write captured BLOB for " + camera.value(), e);
        }
    }
}
```

- [ ] **Step 7.3: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.device.TempDirCameraImageSinkTest'`
Expected: pass.

- [ ] **Step 7.4: Commit**

```bash
git add src/main/java/dev/nocs/device/TempDirCameraImageSink.java \
        src/test/java/dev/nocs/device/TempDirCameraImageSinkTest.java
git commit -m "feat: TempDirCameraImageSink default port impl with image_received event"
```

---

### Task 8: INDI Mount adapter

**Files:**
- Create: `src/main/java/dev/nocs/device/adapter/IndiMountAdapter.java`
- Create: `src/test/java/dev/nocs/device/adapter/IndiMountAdapterTest.java`

INDI mapping:
- Connect/disconnect: `CONNECTION` switch (`CONNECT`/`DISCONNECT`).
- Slew/sync: first set `ON_COORD_SET` (`SLEW`/`TRACK`/`SYNC`), then set `EQUATORIAL_EOD_COORD` with `RA, DEC`.
- Park: `TELESCOPE_PARK` switch (`PARK`/`UNPARK`).
- State derivation: `EQUATORIAL_EOD_COORD.state` — `Busy` → `SLEWING`; `Ok` while moving reports resolved means `TRACKING`; `TELESCOPE_PARK.PARK=On` → `PARKED`; `CONNECTION.DISCONNECT=On` → `DISCONNECTED`.

- [ ] **Step 8.1: Failing test**

`src/test/java/dev/nocs/device/adapter/IndiMountAdapterTest.java`:

```java
package dev.nocs.device.adapter;

import dev.nocs.device.DeviceId;
import dev.nocs.device.MountState;
import dev.nocs.events.EventBus;
import dev.nocs.indi.IndiClient;
import dev.nocs.indi.IndiProperty;
import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

class IndiMountAdapterTest {

    private IndiClient client = mock(IndiClient.class);
    private EventBus bus = new EventBus();

    private IndiMountAdapter mount() {
        return new IndiMountAdapter("Telescope Simulator", new DeviceId("telescope-simulator"), client, bus);
    }

    @Test
    void connectSetsConnectionSwitch() throws Exception {
        IndiMountAdapter m = mount();
        m.connect();

        ArgumentCaptor<Map<String, Boolean>> captor = ArgumentCaptor.forClass(Map.class);
        verify(client).setSwitch(eq("Telescope Simulator"), eq("CONNECTION"), captor.capture());
        assertThat(captor.getValue()).containsEntry("CONNECT", true).containsEntry("DISCONNECT", false);
    }

    @Test
    void slewIssuesCoordSetThenCoords() throws Exception {
        IndiMountAdapter m = mount();
        m.slew(0.712, 41.269);

        verify(client).setSwitch(eq("Telescope Simulator"), eq("ON_COORD_SET"),
                eq(Map.of("SLEW", true, "TRACK", false, "SYNC", false)));
        verify(client).setNumber(eq("Telescope Simulator"), eq("EQUATORIAL_EOD_COORD"),
                eq(Map.of("RA", 0.712, "DEC", 41.269)));
    }

    @Test
    void syncIssuesSyncThenCoords() throws Exception {
        IndiMountAdapter m = mount();
        m.syncTo(1.0, 2.0);

        verify(client).setSwitch(eq("Telescope Simulator"), eq("ON_COORD_SET"),
                eq(Map.of("SLEW", false, "TRACK", false, "SYNC", true)));
        verify(client).setNumber(eq("Telescope Simulator"), eq("EQUATORIAL_EOD_COORD"),
                eq(Map.of("RA", 1.0, "DEC", 2.0)));
    }

    @Test
    void parkIssuesParkSwitch() throws Exception {
        IndiMountAdapter m = mount();
        m.park();

        verify(client).setSwitch(eq("Telescope Simulator"), eq("TELESCOPE_PARK"),
                eq(Map.of("PARK", true, "UNPARK", false)));
    }

    @Test
    void stateTransitionsFromPropertyUpdates() {
        IndiMountAdapter m = mount();
        assertThat(m.state()).isEqualTo(MountState.DISCONNECTED);

        m.onProperty(connection(true));
        assertThat(m.state()).isEqualTo(MountState.IDLE);

        m.onProperty(eqCoord(IndiProperty.State.BUSY));
        assertThat(m.state()).isEqualTo(MountState.SLEWING);

        m.onProperty(eqCoord(IndiProperty.State.OK));
        assertThat(m.state()).isEqualTo(MountState.TRACKING);

        m.onProperty(parkSwitch(true));
        assertThat(m.state()).isEqualTo(MountState.PARKED);
    }

    private IndiProperty connection(boolean connected) {
        return new IndiProperty.SwitchVector(
                "Telescope Simulator", "CONNECTION", IndiProperty.State.OK, Instant.now(),
                IndiProperty.SwitchRule.ONE_OF_MANY,
                Map.of("CONNECT", connected, "DISCONNECT", !connected));
    }

    private IndiProperty eqCoord(IndiProperty.State state) {
        return new IndiProperty.NumberVector(
                "Telescope Simulator", "EQUATORIAL_EOD_COORD", state, Instant.now(),
                Map.of("RA", 0.0, "DEC", 0.0));
    }

    private IndiProperty parkSwitch(boolean parked) {
        return new IndiProperty.SwitchVector(
                "Telescope Simulator", "TELESCOPE_PARK", IndiProperty.State.OK, Instant.now(),
                IndiProperty.SwitchRule.ONE_OF_MANY,
                Map.of("PARK", parked, "UNPARK", !parked));
    }
}
```

Note: `mockito-core` is already present via `spring-boot-starter-test`. No new dependency needed.

- [ ] **Step 8.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.device.adapter.IndiMountAdapterTest'`
Expected: class missing.

- [ ] **Step 8.3: Implement `IndiMountAdapter`**

Create `src/main/java/dev/nocs/device/adapter/IndiMountAdapter.java`:

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

    @Override public DeviceId id() { return id; }
    @Override public String indiName() { return indiName; }
    @Override public DeviceKind kind() { return DeviceKind.MOUNT; }
    @Override public boolean isConnected() { return state.get() != MountState.DISCONNECTED; }
    @Override public MountState state() { return state.get(); }

    @Override
    public void connect() {
        try { client.setSwitch(indiName, "CONNECTION", Map.of("CONNECT", true, "DISCONNECT", false)); }
        catch (IOException e) { throw new RuntimeException("mount connect failed", e); }
    }

    @Override
    public void disconnect() {
        try { client.setSwitch(indiName, "CONNECTION", Map.of("CONNECT", false, "DISCONNECT", true)); }
        catch (IOException e) { throw new RuntimeException("mount disconnect failed", e); }
    }

    @Override
    public void slew(double raHours, double decDegrees) {
        try {
            client.setSwitch(indiName, "ON_COORD_SET", Map.of("SLEW", true, "TRACK", false, "SYNC", false));
            client.setNumber(indiName, "EQUATORIAL_EOD_COORD", Map.of("RA", raHours, "DEC", decDegrees));
        } catch (IOException e) { throw new RuntimeException("slew failed", e); }
    }

    @Override
    public void syncTo(double raHours, double decDegrees) {
        try {
            client.setSwitch(indiName, "ON_COORD_SET", Map.of("SLEW", false, "TRACK", false, "SYNC", true));
            client.setNumber(indiName, "EQUATORIAL_EOD_COORD", Map.of("RA", raHours, "DEC", decDegrees));
        } catch (IOException e) { throw new RuntimeException("sync failed", e); }
    }

    @Override
    public void park() {
        try { client.setSwitch(indiName, "TELESCOPE_PARK", Map.of("PARK", true, "UNPARK", false)); }
        catch (IOException e) { throw new RuntimeException("park failed", e); }
    }

    @Override
    public void unpark() {
        try { client.setSwitch(indiName, "TELESCOPE_PARK", Map.of("PARK", false, "UNPARK", true)); }
        catch (IOException e) { throw new RuntimeException("unpark failed", e); }
    }

    @Override
    public void abort() {
        try { client.setSwitch(indiName, "TELESCOPE_ABORT_MOTION", Map.of("ABORT", true)); }
        catch (IOException e) { throw new RuntimeException("abort failed", e); }
    }

    public void onProperty(IndiProperty p) {
        if (!p.device().equals(indiName)) return;
        MountState next = state.get();
        if (p instanceof IndiProperty.SwitchVector sw) {
            if (sw.name().equals("CONNECTION")) {
                boolean connected = Boolean.TRUE.equals(sw.elements().get("CONNECT"));
                next = connected ? (next == MountState.DISCONNECTED ? MountState.IDLE : next) : MountState.DISCONNECTED;
            } else if (sw.name().equals("TELESCOPE_PARK")) {
                if (Boolean.TRUE.equals(sw.elements().get("PARK"))) next = MountState.PARKED;
                else if (Boolean.TRUE.equals(sw.elements().get("UNPARK"))) next = MountState.IDLE;
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

    private void transition(MountState next) {
        MountState prev = state.getAndSet(next);
        if (prev == next) return;
        DeviceStateChanged payload = new DeviceStateChanged(id, DeviceKind.MOUNT, prev.name(), next.name());
        bus.publish(Event.of(Topic.MOUNT, "state_changed", payload.toPayload()));
    }
}
```

- [ ] **Step 8.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.device.adapter.IndiMountAdapterTest'`
Expected: all five tests pass.

- [ ] **Step 8.5: Commit**

```bash
git add src/main/java/dev/nocs/device/adapter/IndiMountAdapter.java \
        src/test/java/dev/nocs/device/adapter/IndiMountAdapterTest.java
git commit -m "feat: INDI mount adapter with state machine and slew/park/sync"
```

---

### Task 9: INDI Camera adapter + BLOB delivery

**Files:**
- Create: `src/main/java/dev/nocs/device/adapter/IndiCameraAdapter.java`
- Create: `src/test/java/dev/nocs/device/adapter/IndiCameraAdapterTest.java`

INDI mapping:
- Cool: set `CCD_COOLER` (`COOLER_ON`/`COOLER_OFF`) + set `CCD_TEMPERATURE.CCD_TEMPERATURE_VALUE`.
- Expose: set `CCD_EXPOSURE.CCD_EXPOSURE_VALUE`.
- Abort: `CCD_ABORT_EXPOSURE.ABORT`.
- Upload mode: force `UPLOAD_MODE.UPLOAD_CLIENT=On` on connect so we get BLOBs (not server-side files).
- State:
  - `CCD_EXPOSURE.state == BUSY` → `EXPOSING`.
  - BLOB arrival transitions `EXPOSING → DOWNLOADING → IDLE` (we publish a synthetic `image_received` transition; the read-side sees it via `bus` → `CameraImageSink`).
  - `CCD_TEMPERATURE.state == BUSY` and cooler on → `COOLING`; when at setpoint → `READY`.
  - `CONNECTION.CONNECT=On` → initial state `IDLE` if we were `DISCONNECTED`.

- [ ] **Step 9.1: Failing test**

`src/test/java/dev/nocs/device/adapter/IndiCameraAdapterTest.java`:

```java
package dev.nocs.device.adapter;

import dev.nocs.device.CameraImageSink;
import dev.nocs.device.CameraState;
import dev.nocs.device.DeviceId;
import dev.nocs.events.EventBus;
import dev.nocs.indi.IndiClient;
import dev.nocs.indi.IndiProperty;
import java.time.Instant;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

class IndiCameraAdapterTest {

    private final IndiClient client = mock(IndiClient.class);
    private final EventBus bus = new EventBus();
    private final CopyOnWriteArrayList<byte[]> sunk = new CopyOnWriteArrayList<>();
    private final CameraImageSink sink = (camera, bytes, ext) -> sunk.add(bytes);
    private final DeviceId id = new DeviceId("ccd-simulator");

    private IndiCameraAdapter camera() {
        return new IndiCameraAdapter("CCD Simulator", id, client, bus, sink);
    }

    @Test
    void connectForcesUploadClientAndConnectsBlob() throws Exception {
        IndiCameraAdapter c = camera();
        c.connect();

        verify(client).setSwitch(eq("CCD Simulator"), eq("CONNECTION"),
                eq(Map.of("CONNECT", true, "DISCONNECT", false)));
        verify(client).setSwitch(eq("CCD Simulator"), eq("UPLOAD_MODE"),
                eq(Map.of("UPLOAD_CLIENT", true, "UPLOAD_LOCAL", false, "UPLOAD_BOTH", false)));
        verify(client).enableBlob(eq("CCD Simulator"), eq("Also"));
    }

    @Test
    void coolSetsCoolerAndTemperature() throws Exception {
        IndiCameraAdapter c = camera();
        c.cool(-10.0);

        verify(client).setSwitch(eq("CCD Simulator"), eq("CCD_COOLER"),
                eq(Map.of("COOLER_ON", true, "COOLER_OFF", false)));
        verify(client).setNumber(eq("CCD Simulator"), eq("CCD_TEMPERATURE"),
                eq(Map.of("CCD_TEMPERATURE_VALUE", -10.0)));
    }

    @Test
    void exposeSetsExposureNumber() throws Exception {
        IndiCameraAdapter c = camera();
        c.expose(2.5);

        verify(client).setNumber(eq("CCD Simulator"), eq("CCD_EXPOSURE"),
                eq(Map.of("CCD_EXPOSURE_VALUE", 2.5)));
    }

    @Test
    void stateTransitionsOnProperties() {
        IndiCameraAdapter c = camera();
        assertThat(c.state()).isEqualTo(CameraState.DISCONNECTED);

        c.onProperty(connection(true));
        assertThat(c.state()).isEqualTo(CameraState.IDLE);

        c.onProperty(exposureVector(IndiProperty.State.BUSY, 1.0));
        assertThat(c.state()).isEqualTo(CameraState.EXPOSING);

        c.onBlob(new byte[]{7, 8, 9}, ".fits");
        assertThat(sunk).hasSize(1);
        assertThat(c.state()).isEqualTo(CameraState.IDLE);
    }

    private IndiProperty connection(boolean connected) {
        return new IndiProperty.SwitchVector("CCD Simulator", "CONNECTION",
                IndiProperty.State.OK, Instant.now(),
                IndiProperty.SwitchRule.ONE_OF_MANY,
                Map.of("CONNECT", connected, "DISCONNECT", !connected));
    }

    private IndiProperty exposureVector(IndiProperty.State state, double value) {
        return new IndiProperty.NumberVector("CCD Simulator", "CCD_EXPOSURE", state, Instant.now(),
                Map.of("CCD_EXPOSURE_VALUE", value));
    }
}
```

- [ ] **Step 9.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.device.adapter.IndiCameraAdapterTest'`
Expected: class missing.

- [ ] **Step 9.3: Implement `IndiCameraAdapter`**

Create `src/main/java/dev/nocs/device/adapter/IndiCameraAdapter.java`:

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

    @Override public DeviceId id() { return id; }
    @Override public String indiName() { return indiName; }
    @Override public DeviceKind kind() { return DeviceKind.CAMERA; }
    @Override public boolean isConnected() { return state.get() != CameraState.DISCONNECTED; }
    @Override public CameraState state() { return state.get(); }
    @Override public Double currentTemperatureCelsius() { return lastTemp; }

    @Override
    public void connect() {
        try {
            client.setSwitch(indiName, "CONNECTION", Map.of("CONNECT", true, "DISCONNECT", false));
            client.setSwitch(indiName, "UPLOAD_MODE",
                    Map.of("UPLOAD_CLIENT", true, "UPLOAD_LOCAL", false, "UPLOAD_BOTH", false));
            client.enableBlob(indiName, "Also");
        } catch (IOException e) { throw new RuntimeException("camera connect failed", e); }
    }

    @Override
    public void disconnect() {
        try { client.setSwitch(indiName, "CONNECTION", Map.of("CONNECT", false, "DISCONNECT", true)); }
        catch (IOException e) { throw new RuntimeException("camera disconnect failed", e); }
    }

    @Override
    public void cool(double setpointCelsius) {
        try {
            client.setSwitch(indiName, "CCD_COOLER", Map.of("COOLER_ON", true, "COOLER_OFF", false));
            client.setNumber(indiName, "CCD_TEMPERATURE", Map.of("CCD_TEMPERATURE_VALUE", setpointCelsius));
        } catch (IOException e) { throw new RuntimeException("camera cool failed", e); }
    }

    @Override
    public void expose(double durationSeconds) {
        try { client.setNumber(indiName, "CCD_EXPOSURE", Map.of("CCD_EXPOSURE_VALUE", durationSeconds)); }
        catch (IOException e) { throw new RuntimeException("expose failed", e); }
    }

    @Override
    public void abortExposure() {
        try { client.setSwitch(indiName, "CCD_ABORT_EXPOSURE", Map.of("ABORT", true)); }
        catch (IOException e) { throw new RuntimeException("abort exposure failed", e); }
    }

    public void onProperty(IndiProperty p) {
        if (!p.device().equals(indiName)) return;
        CameraState next = state.get();
        if (p instanceof IndiProperty.SwitchVector sw && sw.name().equals("CONNECTION")) {
            boolean connected = Boolean.TRUE.equals(sw.elements().get("CONNECT"));
            next = connected ? (next == CameraState.DISCONNECTED ? CameraState.IDLE : next) : CameraState.DISCONNECTED;
        } else if (p instanceof IndiProperty.NumberVector n) {
            if (n.name().equals("CCD_EXPOSURE")) {
                if (n.state() == IndiProperty.State.BUSY) next = CameraState.EXPOSING;
                else if (n.state() == IndiProperty.State.ALERT) next = CameraState.ERROR;
            } else if (n.name().equals("CCD_TEMPERATURE")) {
                Double t = n.elements().get("CCD_TEMPERATURE_VALUE");
                if (t != null) lastTemp = t;
                if (n.state() == IndiProperty.State.BUSY) next = CameraState.COOLING;
                else if (n.state() == IndiProperty.State.OK && state.get() == CameraState.COOLING) next = CameraState.READY;
            }
        }
        transition(next);
    }

    public void onBlob(byte[] bytes, String format) {
        CameraState prev = state.getAndSet(CameraState.DOWNLOADING);
        if (prev != CameraState.DOWNLOADING) publishStateEvent(prev, CameraState.DOWNLOADING);
        sink.accept(id, bytes, format);
        transition(CameraState.IDLE);
    }

    private void transition(CameraState next) {
        CameraState prev = state.getAndSet(next);
        if (prev == next) return;
        publishStateEvent(prev, next);
    }

    private void publishStateEvent(CameraState prev, CameraState next) {
        DeviceStateChanged payload = new DeviceStateChanged(id, DeviceKind.CAMERA, prev.name(), next.name());
        bus.publish(Event.of(Topic.CAMERA, "state_changed", payload.toPayload()));
    }
}
```

- [ ] **Step 9.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.device.adapter.IndiCameraAdapterTest'`
Expected: all four tests pass.

- [ ] **Step 9.5: Commit**

```bash
git add src/main/java/dev/nocs/device/adapter/IndiCameraAdapter.java \
        src/test/java/dev/nocs/device/adapter/IndiCameraAdapterTest.java
git commit -m "feat: INDI camera adapter with BLOB delivery to CameraImageSink"
```

---

### Task 10: INDI FilterWheel adapter

**Files:**
- Create: `src/main/java/dev/nocs/device/adapter/IndiFilterWheelAdapter.java`
- Create: `src/test/java/dev/nocs/device/adapter/IndiFilterWheelAdapterTest.java`

INDI mapping:
- `FILTER_SLOT.FILTER_SLOT_VALUE` — current slot (1-based).
- `FILTER_NAME.FILTER_SLOT_NAME_*` — labels (optional).
- State: `FILTER_SLOT.state == BUSY` → `MOVING`, else `IDLE` (when connected).

- [ ] **Step 10.1: Failing test**

`src/test/java/dev/nocs/device/adapter/IndiFilterWheelAdapterTest.java`:

```java
package dev.nocs.device.adapter;

import dev.nocs.device.DeviceId;
import dev.nocs.device.FilterWheelState;
import dev.nocs.events.EventBus;
import dev.nocs.indi.IndiClient;
import dev.nocs.indi.IndiProperty;
import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

class IndiFilterWheelAdapterTest {

    private final IndiClient client = mock(IndiClient.class);
    private final EventBus bus = new EventBus();

    private IndiFilterWheelAdapter wheel() {
        return new IndiFilterWheelAdapter("Filter Simulator",
                new DeviceId("filter-simulator"), client, bus);
    }

    @Test
    void selectSlotIssuesNumber() throws Exception {
        IndiFilterWheelAdapter w = wheel();
        w.selectSlot(3);
        verify(client).setNumber(eq("Filter Simulator"), eq("FILTER_SLOT"),
                eq(Map.of("FILTER_SLOT_VALUE", 3.0)));
    }

    @Test
    void movesAndSettles() {
        IndiFilterWheelAdapter w = wheel();
        w.onProperty(connection(true));
        assertThat(w.state()).isEqualTo(FilterWheelState.IDLE);

        w.onProperty(slotVector(IndiProperty.State.BUSY, 2));
        assertThat(w.state()).isEqualTo(FilterWheelState.MOVING);

        w.onProperty(slotVector(IndiProperty.State.OK, 2));
        assertThat(w.state()).isEqualTo(FilterWheelState.IDLE);
        assertThat(w.currentSlot()).isEqualTo(2);
    }

    private IndiProperty connection(boolean connected) {
        return new IndiProperty.SwitchVector("Filter Simulator", "CONNECTION",
                IndiProperty.State.OK, Instant.now(),
                IndiProperty.SwitchRule.ONE_OF_MANY,
                Map.of("CONNECT", connected, "DISCONNECT", !connected));
    }

    private IndiProperty slotVector(IndiProperty.State state, int value) {
        return new IndiProperty.NumberVector("Filter Simulator", "FILTER_SLOT",
                state, Instant.now(),
                Map.of("FILTER_SLOT_VALUE", (double) value));
    }
}
```

- [ ] **Step 10.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.device.adapter.IndiFilterWheelAdapterTest'`
Expected: class missing.

- [ ] **Step 10.3: Implement**

Create `src/main/java/dev/nocs/device/adapter/IndiFilterWheelAdapter.java`:

```java
package dev.nocs.device.adapter;

import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceKind;
import dev.nocs.device.DeviceStateChanged;
import dev.nocs.device.FilterWheel;
import dev.nocs.device.FilterWheelState;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.indi.IndiClient;
import dev.nocs.indi.IndiProperty;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

public class IndiFilterWheelAdapter implements FilterWheel {

    private final String indiName;
    private final DeviceId id;
    private final IndiClient client;
    private final EventBus bus;
    private final AtomicReference<FilterWheelState> state = new AtomicReference<>(FilterWheelState.DISCONNECTED);
    private final AtomicInteger slot = new AtomicInteger();
    private volatile List<String> names = List.of();

    public IndiFilterWheelAdapter(String indiName, DeviceId id, IndiClient client, EventBus bus) {
        this.indiName = indiName;
        this.id = id;
        this.client = client;
        this.bus = bus;
    }

    @Override public DeviceId id() { return id; }
    @Override public String indiName() { return indiName; }
    @Override public DeviceKind kind() { return DeviceKind.FILTERWHEEL; }
    @Override public boolean isConnected() { return state.get() != FilterWheelState.DISCONNECTED; }
    @Override public FilterWheelState state() { return state.get(); }
    @Override public List<String> slotNames() { return names; }
    @Override public int currentSlot() { return slot.get(); }

    @Override
    public void connect() {
        try { client.setSwitch(indiName, "CONNECTION", Map.of("CONNECT", true, "DISCONNECT", false)); }
        catch (IOException e) { throw new RuntimeException("filterwheel connect failed", e); }
    }

    @Override
    public void disconnect() {
        try { client.setSwitch(indiName, "CONNECTION", Map.of("CONNECT", false, "DISCONNECT", true)); }
        catch (IOException e) { throw new RuntimeException("filterwheel disconnect failed", e); }
    }

    @Override
    public void selectSlot(int slotNumber) {
        try { client.setNumber(indiName, "FILTER_SLOT", Map.of("FILTER_SLOT_VALUE", (double) slotNumber)); }
        catch (IOException e) { throw new RuntimeException("selectSlot failed", e); }
    }

    public void onProperty(IndiProperty p) {
        if (!p.device().equals(indiName)) return;
        FilterWheelState next = state.get();
        if (p instanceof IndiProperty.SwitchVector sw && sw.name().equals("CONNECTION")) {
            boolean connected = Boolean.TRUE.equals(sw.elements().get("CONNECT"));
            next = connected ? (next == FilterWheelState.DISCONNECTED ? FilterWheelState.IDLE : next) : FilterWheelState.DISCONNECTED;
        } else if (p instanceof IndiProperty.NumberVector n && n.name().equals("FILTER_SLOT")) {
            Double v = n.elements().get("FILTER_SLOT_VALUE");
            if (v != null) slot.set((int) Math.round(v));
            next = switch (n.state()) {
                case BUSY -> FilterWheelState.MOVING;
                case OK, IDLE -> FilterWheelState.IDLE;
                case ALERT -> FilterWheelState.ERROR;
            };
        } else if (p instanceof IndiProperty.TextVector t && t.name().equals("FILTER_NAME")) {
            List<String> newNames = new ArrayList<>(t.elements().values());
            names = List.copyOf(newNames);
        }
        transition(next);
    }

    private void transition(FilterWheelState next) {
        FilterWheelState prev = state.getAndSet(next);
        if (prev == next) return;
        DeviceStateChanged payload = new DeviceStateChanged(id, DeviceKind.FILTERWHEEL, prev.name(), next.name());
        bus.publish(Event.of(Topic.FILTERWHEEL, "state_changed", payload.toPayload()));
    }
}
```

- [ ] **Step 10.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.device.adapter.IndiFilterWheelAdapterTest'`
Expected: two tests pass.

- [ ] **Step 10.5: Commit**

```bash
git add src/main/java/dev/nocs/device/adapter/IndiFilterWheelAdapter.java \
        src/test/java/dev/nocs/device/adapter/IndiFilterWheelAdapterTest.java
git commit -m "feat: INDI filter wheel adapter with slot move semantics"
```

---

### Task 11: INDI Focuser adapter

**Files:**
- Create: `src/main/java/dev/nocs/device/adapter/IndiFocuserAdapter.java`
- Create: `src/test/java/dev/nocs/device/adapter/IndiFocuserAdapterTest.java`

INDI mapping:
- `ABS_FOCUS_POSITION.FOCUS_ABSOLUTE_POSITION` for absolute move.
- `REL_FOCUS_POSITION.FOCUS_RELATIVE_POSITION` for relative move (most INDI focusers require a separate `FOCUS_MOTION.FOCUS_INWARD/OUTWARD` switch for relative sign; v0.1 sends absolute on the resolved target and ignores relative-direction switch, computing: absolute = current + delta).
- `FOCUS_ABORT_MOTION.ABORT` for abort.
- State: `ABS_FOCUS_POSITION.state == BUSY` → `MOVING`, else `IDLE`.

- [ ] **Step 11.1: Failing test**

`src/test/java/dev/nocs/device/adapter/IndiFocuserAdapterTest.java`:

```java
package dev.nocs.device.adapter;

import dev.nocs.device.DeviceId;
import dev.nocs.device.FocuserState;
import dev.nocs.events.EventBus;
import dev.nocs.indi.IndiClient;
import dev.nocs.indi.IndiProperty;
import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

class IndiFocuserAdapterTest {

    private final IndiClient client = mock(IndiClient.class);
    private final EventBus bus = new EventBus();

    private IndiFocuserAdapter focuser() {
        return new IndiFocuserAdapter("Focuser Simulator",
                new DeviceId("focuser-simulator"), client, bus);
    }

    @Test
    void moveAbsoluteIssuesNumber() throws Exception {
        IndiFocuserAdapter f = focuser();
        f.moveAbsolute(12500);
        verify(client).setNumber(eq("Focuser Simulator"), eq("ABS_FOCUS_POSITION"),
                eq(Map.of("FOCUS_ABSOLUTE_POSITION", 12500.0)));
    }

    @Test
    void moveRelativeComputesAbsoluteFromCurrent() throws Exception {
        IndiFocuserAdapter f = focuser();
        f.onProperty(absPos(IndiProperty.State.OK, 10000));
        reset(client);

        f.moveRelative(-200);
        verify(client).setNumber(eq("Focuser Simulator"), eq("ABS_FOCUS_POSITION"),
                eq(Map.of("FOCUS_ABSOLUTE_POSITION", 9800.0)));
    }

    @Test
    void stateFollowsAbsPosition() {
        IndiFocuserAdapter f = focuser();
        f.onProperty(connection(true));
        assertThat(f.state()).isEqualTo(FocuserState.IDLE);

        f.onProperty(absPos(IndiProperty.State.BUSY, 11000));
        assertThat(f.state()).isEqualTo(FocuserState.MOVING);

        f.onProperty(absPos(IndiProperty.State.OK, 11000));
        assertThat(f.state()).isEqualTo(FocuserState.IDLE);
        assertThat(f.currentPosition()).isEqualTo(11000);
    }

    private IndiProperty connection(boolean connected) {
        return new IndiProperty.SwitchVector("Focuser Simulator", "CONNECTION",
                IndiProperty.State.OK, Instant.now(),
                IndiProperty.SwitchRule.ONE_OF_MANY,
                Map.of("CONNECT", connected, "DISCONNECT", !connected));
    }

    private IndiProperty absPos(IndiProperty.State state, int pos) {
        return new IndiProperty.NumberVector("Focuser Simulator", "ABS_FOCUS_POSITION",
                state, Instant.now(),
                Map.of("FOCUS_ABSOLUTE_POSITION", (double) pos));
    }
}
```

- [ ] **Step 11.2: Run — expect failure**

Run: `./gradlew test --tests 'dev.nocs.device.adapter.IndiFocuserAdapterTest'`
Expected: class missing.

- [ ] **Step 11.3: Implement**

Create `src/main/java/dev/nocs/device/adapter/IndiFocuserAdapter.java`:

```java
package dev.nocs.device.adapter;

import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceKind;
import dev.nocs.device.DeviceStateChanged;
import dev.nocs.device.Focuser;
import dev.nocs.device.FocuserState;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.indi.IndiClient;
import dev.nocs.indi.IndiProperty;
import java.io.IOException;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

public class IndiFocuserAdapter implements Focuser {

    private final String indiName;
    private final DeviceId id;
    private final IndiClient client;
    private final EventBus bus;
    private final AtomicReference<FocuserState> state = new AtomicReference<>(FocuserState.DISCONNECTED);
    private final AtomicInteger position = new AtomicInteger();

    public IndiFocuserAdapter(String indiName, DeviceId id, IndiClient client, EventBus bus) {
        this.indiName = indiName;
        this.id = id;
        this.client = client;
        this.bus = bus;
    }

    @Override public DeviceId id() { return id; }
    @Override public String indiName() { return indiName; }
    @Override public DeviceKind kind() { return DeviceKind.FOCUSER; }
    @Override public boolean isConnected() { return state.get() != FocuserState.DISCONNECTED; }
    @Override public FocuserState state() { return state.get(); }
    @Override public int currentPosition() { return position.get(); }

    @Override
    public void connect() {
        try { client.setSwitch(indiName, "CONNECTION", Map.of("CONNECT", true, "DISCONNECT", false)); }
        catch (IOException e) { throw new RuntimeException("focuser connect failed", e); }
    }

    @Override
    public void disconnect() {
        try { client.setSwitch(indiName, "CONNECTION", Map.of("CONNECT", false, "DISCONNECT", true)); }
        catch (IOException e) { throw new RuntimeException("focuser disconnect failed", e); }
    }

    @Override
    public void moveAbsolute(int pos) {
        try { client.setNumber(indiName, "ABS_FOCUS_POSITION", Map.of("FOCUS_ABSOLUTE_POSITION", (double) pos)); }
        catch (IOException e) { throw new RuntimeException("moveAbsolute failed", e); }
    }

    @Override
    public void moveRelative(int delta) {
        moveAbsolute(position.get() + delta);
    }

    @Override
    public void abort() {
        try { client.setSwitch(indiName, "FOCUS_ABORT_MOTION", Map.of("ABORT", true)); }
        catch (IOException e) { throw new RuntimeException("focuser abort failed", e); }
    }

    public void onProperty(IndiProperty p) {
        if (!p.device().equals(indiName)) return;
        FocuserState next = state.get();
        if (p instanceof IndiProperty.SwitchVector sw && sw.name().equals("CONNECTION")) {
            boolean connected = Boolean.TRUE.equals(sw.elements().get("CONNECT"));
            next = connected ? (next == FocuserState.DISCONNECTED ? FocuserState.IDLE : next) : FocuserState.DISCONNECTED;
        } else if (p instanceof IndiProperty.NumberVector n && n.name().equals("ABS_FOCUS_POSITION")) {
            Double v = n.elements().get("FOCUS_ABSOLUTE_POSITION");
            if (v != null) position.set((int) Math.round(v));
            next = switch (n.state()) {
                case BUSY -> FocuserState.MOVING;
                case OK, IDLE -> FocuserState.IDLE;
                case ALERT -> FocuserState.ERROR;
            };
        }
        transition(next);
    }

    private void transition(FocuserState next) {
        FocuserState prev = state.getAndSet(next);
        if (prev == next) return;
        DeviceStateChanged payload = new DeviceStateChanged(id, DeviceKind.FOCUSER, prev.name(), next.name());
        bus.publish(Event.of(Topic.FOCUSER, "state_changed", payload.toPayload()));
    }
}
```

- [ ] **Step 11.4: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.device.adapter.IndiFocuserAdapterTest'`
Expected: three tests pass.

- [ ] **Step 11.5: Commit**

```bash
git add src/main/java/dev/nocs/device/adapter/IndiFocuserAdapter.java \
        src/test/java/dev/nocs/device/adapter/IndiFocuserAdapterTest.java
git commit -m "feat: INDI focuser adapter with absolute/relative moves"
```

---

### Task 12: `DeviceService`, `DeviceRegistry`, `IndiDeviceFactory`, REST controllers

**Files:**
- Create: `src/main/java/dev/nocs/device/adapter/IndiDeviceFactory.java`
- Create: `src/main/java/dev/nocs/device/DeviceRegistry.java`
- Create: `src/main/java/dev/nocs/device/DeviceService.java`
- Create: `src/main/java/dev/nocs/device/api/dto/DeviceView.java`
- Create: `src/main/java/dev/nocs/device/api/dto/SlewRequest.java`
- Create: `src/main/java/dev/nocs/device/api/dto/CoolRequest.java`
- Create: `src/main/java/dev/nocs/device/api/dto/ExposeRequest.java`
- Create: `src/main/java/dev/nocs/device/api/dto/SelectSlotRequest.java`
- Create: `src/main/java/dev/nocs/device/api/dto/MoveRequest.java`
- Create: `src/main/java/dev/nocs/device/api/DeviceController.java`
- Create: `src/main/java/dev/nocs/device/api/MountController.java`
- Create: `src/main/java/dev/nocs/device/api/CameraController.java`
- Create: `src/main/java/dev/nocs/device/api/FilterWheelController.java`
- Create: `src/main/java/dev/nocs/device/api/FocuserController.java`
- Create: `src/test/java/dev/nocs/device/api/DeviceControllerTest.java`
- Create: `src/test/java/dev/nocs/device/api/MountControllerTest.java`
- Create: `src/test/java/dev/nocs/device/api/CameraControllerTest.java`
- Create: `src/test/java/dev/nocs/device/api/FilterWheelControllerTest.java`
- Create: `src/test/java/dev/nocs/device/api/FocuserControllerTest.java`
- Modify: `src/main/java/dev/nocs/NocsApplication.java` (create `IndiClient` + `IndiServerSupervisor` beans, auto-start based on `nocs.indi.mode`)

Device-kind detection rule for `IndiDeviceFactory`: given the set of INDI property names advertised for a device,

- any of `EQUATORIAL_EOD_COORD`, `TELESCOPE_PARK`, `TELESCOPE_ABORT_MOTION` → MOUNT
- any of `CCD_EXPOSURE`, `CCD_TEMPERATURE`, `CCD1` → CAMERA
- `FILTER_SLOT` → FILTERWHEEL
- `ABS_FOCUS_POSITION` or `REL_FOCUS_POSITION` → FOCUSER
- otherwise UNKNOWN (skipped).

- [ ] **Step 12.1: Failing test — `DeviceControllerTest`**

```java
package dev.nocs.device.api;

import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceKind;
import dev.nocs.device.DeviceService;
import dev.nocs.device.MountState;
import dev.nocs.device.adapter.IndiMountAdapter;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(properties = "nocs.auth.token=t")
class DeviceControllerTest {

    @Autowired MockMvc mvc;
    @MockitoBean DeviceService service;

    @BeforeEach
    void setup() {
        IndiMountAdapter m = mock(IndiMountAdapter.class);
        when(m.id()).thenReturn(new DeviceId("telescope-simulator"));
        when(m.kind()).thenReturn(DeviceKind.MOUNT);
        when(m.indiName()).thenReturn("Telescope Simulator");
        when(m.state()).thenReturn(MountState.IDLE);
        when(m.isConnected()).thenReturn(true);
        when(service.list()).thenReturn(java.util.List.of(m));
    }

    @Test
    void listReturnsJson() throws Exception {
        mvc.perform(get("/api/devices").header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].id").value("telescope-simulator"))
                .andExpect(jsonPath("$[0].kind").value("mount"))
                .andExpect(jsonPath("$[0].state").value("IDLE"));
    }

    @Test
    void connectInvokesService() throws Exception {
        mvc.perform(post("/api/devices/telescope-simulator/connect").header("Authorization", "Bearer t"))
                .andExpect(status().isOk());
        verify(service).connect(new DeviceId("telescope-simulator"));
    }

    @Test
    void disconnectInvokesService() throws Exception {
        mvc.perform(post("/api/devices/telescope-simulator/disconnect").header("Authorization", "Bearer t"))
                .andExpect(status().isOk());
        verify(service).disconnect(new DeviceId("telescope-simulator"));
    }
}
```

Failing-test counterparts for the kind-specific controllers follow the same pattern — each one mocks the `DeviceService` to return the right adapter type and asserts the HTTP→method mapping. See the code listings below for each and mirror them in tests.

- [ ] **Step 12.2: Implement DTOs**

`src/main/java/dev/nocs/device/api/dto/DeviceView.java`:

```java
package dev.nocs.device.api.dto;

public record DeviceView(String id, String indiName, String kind, String state, boolean connected) {}
```

`src/main/java/dev/nocs/device/api/dto/SlewRequest.java`:

```java
package dev.nocs.device.api.dto;

public record SlewRequest(double raHours, double decDegrees) {}
```

`src/main/java/dev/nocs/device/api/dto/CoolRequest.java`:

```java
package dev.nocs.device.api.dto;

public record CoolRequest(double setpointCelsius) {}
```

`src/main/java/dev/nocs/device/api/dto/ExposeRequest.java`:

```java
package dev.nocs.device.api.dto;

public record ExposeRequest(double durationSeconds) {}
```

`src/main/java/dev/nocs/device/api/dto/SelectSlotRequest.java`:

```java
package dev.nocs.device.api.dto;

public record SelectSlotRequest(int slot) {}
```

`src/main/java/dev/nocs/device/api/dto/MoveRequest.java`:

```java
package dev.nocs.device.api.dto;

public record MoveRequest(Integer position, Integer offset) {}
```

- [ ] **Step 12.3: Implement `IndiDeviceFactory`**

`src/main/java/dev/nocs/device/adapter/IndiDeviceFactory.java`:

```java
package dev.nocs.device.adapter;

import dev.nocs.device.CameraImageSink;
import dev.nocs.device.Device;
import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceKind;
import dev.nocs.events.EventBus;
import dev.nocs.indi.IndiClient;
import dev.nocs.indi.IndiProperty;
import java.util.Collection;
import java.util.Set;
import java.util.stream.Collectors;

public final class IndiDeviceFactory {

    private static final Set<String> MOUNT_HINTS =
            Set.of("EQUATORIAL_EOD_COORD", "TELESCOPE_PARK", "TELESCOPE_ABORT_MOTION");
    private static final Set<String> CAMERA_HINTS =
            Set.of("CCD_EXPOSURE", "CCD_TEMPERATURE", "CCD1");
    private static final Set<String> FILTER_HINTS = Set.of("FILTER_SLOT");
    private static final Set<String> FOCUSER_HINTS =
            Set.of("ABS_FOCUS_POSITION", "REL_FOCUS_POSITION");

    private IndiDeviceFactory() {}

    public static DeviceKind classify(Collection<IndiProperty> props) {
        Set<String> names = props.stream().map(IndiProperty::name).collect(Collectors.toSet());
        if (names.stream().anyMatch(MOUNT_HINTS::contains)) return DeviceKind.MOUNT;
        if (names.stream().anyMatch(CAMERA_HINTS::contains)) return DeviceKind.CAMERA;
        if (names.stream().anyMatch(FILTER_HINTS::contains)) return DeviceKind.FILTERWHEEL;
        if (names.stream().anyMatch(FOCUSER_HINTS::contains)) return DeviceKind.FOCUSER;
        return DeviceKind.UNKNOWN;
    }

    public static Device create(
            String indiName, Collection<IndiProperty> props,
            IndiClient client, EventBus bus, CameraImageSink sink) {
        DeviceId id = DeviceId.slug(indiName);
        return switch (classify(props)) {
            case MOUNT -> new IndiMountAdapter(indiName, id, client, bus);
            case CAMERA -> new IndiCameraAdapter(indiName, id, client, bus, sink);
            case FILTERWHEEL -> new IndiFilterWheelAdapter(indiName, id, client, bus);
            case FOCUSER -> new IndiFocuserAdapter(indiName, id, client, bus);
            case UNKNOWN -> null;
        };
    }
}
```

- [ ] **Step 12.4: Implement `DeviceRegistry`**

`src/main/java/dev/nocs/device/DeviceRegistry.java`:

```java
package dev.nocs.device;

import java.util.Collection;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

public class DeviceRegistry {

    private final Map<DeviceId, Device> devices = new ConcurrentHashMap<>();

    public void add(Device d) { devices.put(d.id(), d); }
    public void remove(DeviceId id) { devices.remove(id); }
    public Optional<Device> find(DeviceId id) { return Optional.ofNullable(devices.get(id)); }
    public Collection<Device> all() { return devices.values(); }

    public Optional<Mount> mount(DeviceId id) {
        return find(id).filter(d -> d.kind() == DeviceKind.MOUNT).map(Mount.class::cast);
    }
    public Optional<Camera> camera(DeviceId id) {
        return find(id).filter(d -> d.kind() == DeviceKind.CAMERA).map(Camera.class::cast);
    }
    public Optional<FilterWheel> filterWheel(DeviceId id) {
        return find(id).filter(d -> d.kind() == DeviceKind.FILTERWHEEL).map(FilterWheel.class::cast);
    }
    public Optional<Focuser> focuser(DeviceId id) {
        return find(id).filter(d -> d.kind() == DeviceKind.FOCUSER).map(Focuser.class::cast);
    }
}
```

- [ ] **Step 12.5: Implement `DeviceService`**

`src/main/java/dev/nocs/device/DeviceService.java`:

```java
package dev.nocs.device;

import dev.nocs.device.adapter.IndiCameraAdapter;
import dev.nocs.device.adapter.IndiDeviceFactory;
import dev.nocs.device.adapter.IndiFilterWheelAdapter;
import dev.nocs.device.adapter.IndiFocuserAdapter;
import dev.nocs.device.adapter.IndiMountAdapter;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.indi.IndiClient;
import dev.nocs.indi.IndiProperty;
import dev.nocs.indi.PropertyUpdate;
import jakarta.annotation.PreDestroy;
import java.util.Collection;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.concurrent.ConcurrentHashMap;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class DeviceService {

    private static final Logger log = LoggerFactory.getLogger(DeviceService.class);

    private final IndiClient client;
    private final EventBus bus;
    private final CameraImageSink sink;
    private final DeviceRegistry registry = new DeviceRegistry();
    private final Map<String, DeviceId> deviceIdsByIndiName = new ConcurrentHashMap<>();
    private final reactor.core.Disposable subscription;

    public DeviceService(IndiClient client, EventBus bus, CameraImageSink sink) {
        this.client = client;
        this.bus = bus;
        this.sink = sink;
        this.subscription = client.updates().subscribe(this::onUpdate);
        client.onBlob((device, propertyName, format, bytes) -> {
            DeviceId id = deviceIdsByIndiName.get(device);
            if (id == null) { sink.accept(DeviceId.slug(device), bytes, format); return; }
            Device d = registry.find(id).orElse(null);
            if (d instanceof IndiCameraAdapter cam) cam.onBlob(bytes, format);
            else sink.accept(id, bytes, format);
        });
    }

    public DeviceRegistry registry() { return registry; }

    public Collection<Device> list() { return registry.all(); }

    public void connect(DeviceId id) {
        device(id).connect();
    }

    public void disconnect(DeviceId id) {
        device(id).disconnect();
    }

    private Device device(DeviceId id) {
        return registry.find(id).orElseThrow(() -> new NoSuchElementException("unknown device: " + id.value()));
    }

    private void onUpdate(PropertyUpdate update) {
        IndiProperty p = update.property();
        DeviceId id = deviceIdsByIndiName.computeIfAbsent(p.device(), DeviceId::slug);
        if (!registry.find(id).isPresent()) {
            Device d = IndiDeviceFactory.create(p.device(), client.properties(p.device()), client, bus, sink);
            if (d == null) { return; }
            registry.add(d);
            bus.publish(Event.of(Topic.DEVICE_CONNECTION, "discovered", Map.of(
                    "id", id.value(), "indiName", p.device(), "kind", d.kind().name().toLowerCase())));
        }
        Device d = registry.find(id).orElse(null);
        if (d instanceof IndiMountAdapter a) a.onProperty(p);
        else if (d instanceof IndiCameraAdapter a) a.onProperty(p);
        else if (d instanceof IndiFilterWheelAdapter a) a.onProperty(p);
        else if (d instanceof IndiFocuserAdapter a) a.onProperty(p);
    }

    @PreDestroy
    public void shutdown() {
        try { subscription.dispose(); } catch (Exception ignored) {}
        try { client.close(); } catch (Exception ignored) {}
    }
}
```

- [ ] **Step 12.6: Implement REST controllers**

`src/main/java/dev/nocs/device/api/DeviceController.java`:

```java
package dev.nocs.device.api;

import dev.nocs.device.Device;
import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceService;
import dev.nocs.device.api.dto.DeviceView;
import java.util.List;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/devices")
public class DeviceController {

    private final DeviceService service;
    public DeviceController(DeviceService service) { this.service = service; }

    @GetMapping
    public List<DeviceView> list() {
        return service.list().stream().map(DeviceController::view).toList();
    }

    @PostMapping("/{id}/connect")
    public void connect(@PathVariable String id) { service.connect(new DeviceId(id)); }

    @PostMapping("/{id}/disconnect")
    public void disconnect(@PathVariable String id) { service.disconnect(new DeviceId(id)); }

    private static DeviceView view(Device d) {
        String state = switch (d.kind()) {
            case MOUNT -> ((dev.nocs.device.Mount) d).state().name();
            case CAMERA -> ((dev.nocs.device.Camera) d).state().name();
            case FILTERWHEEL -> ((dev.nocs.device.FilterWheel) d).state().name();
            case FOCUSER -> ((dev.nocs.device.Focuser) d).state().name();
            case UNKNOWN -> "UNKNOWN";
        };
        return new DeviceView(d.id().value(), d.indiName(), d.kind().name().toLowerCase(), state, d.isConnected());
    }
}
```

`src/main/java/dev/nocs/device/api/MountController.java`:

```java
package dev.nocs.device.api;

import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceService;
import dev.nocs.device.Mount;
import dev.nocs.device.api.dto.SlewRequest;
import java.util.NoSuchElementException;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/mounts/{id}")
public class MountController {

    private final DeviceService service;
    public MountController(DeviceService service) { this.service = service; }

    @PostMapping("/slew")
    public void slew(@PathVariable String id, @RequestBody SlewRequest req) {
        mount(id).slew(req.raHours(), req.decDegrees());
    }

    @PostMapping("/park")
    public void park(@PathVariable String id) { mount(id).park(); }

    @PostMapping("/sync")
    public void sync(@PathVariable String id, @RequestBody SlewRequest req) {
        mount(id).syncTo(req.raHours(), req.decDegrees());
    }

    private Mount mount(String id) {
        return service.registry().mount(new DeviceId(id))
                .orElseThrow(() -> new NoSuchElementException("no mount: " + id));
    }
}
```

`src/main/java/dev/nocs/device/api/CameraController.java`:

```java
package dev.nocs.device.api;

import dev.nocs.device.Camera;
import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceService;
import dev.nocs.device.api.dto.CoolRequest;
import dev.nocs.device.api.dto.ExposeRequest;
import java.util.NoSuchElementException;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/cameras/{id}")
public class CameraController {

    private final DeviceService service;
    public CameraController(DeviceService service) { this.service = service; }

    @PostMapping("/expose")
    public void expose(@PathVariable String id, @RequestBody ExposeRequest req) {
        camera(id).expose(req.durationSeconds());
    }

    @PostMapping("/cool")
    public void cool(@PathVariable String id, @RequestBody CoolRequest req) {
        camera(id).cool(req.setpointCelsius());
    }

    private Camera camera(String id) {
        return service.registry().camera(new DeviceId(id))
                .orElseThrow(() -> new NoSuchElementException("no camera: " + id));
    }
}
```

`src/main/java/dev/nocs/device/api/FilterWheelController.java`:

```java
package dev.nocs.device.api;

import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceService;
import dev.nocs.device.FilterWheel;
import dev.nocs.device.api.dto.SelectSlotRequest;
import java.util.NoSuchElementException;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/filterwheels/{id}")
public class FilterWheelController {

    private final DeviceService service;
    public FilterWheelController(DeviceService service) { this.service = service; }

    @PostMapping("/select")
    public void select(@PathVariable String id, @RequestBody SelectSlotRequest req) {
        wheel(id).selectSlot(req.slot());
    }

    private FilterWheel wheel(String id) {
        return service.registry().filterWheel(new DeviceId(id))
                .orElseThrow(() -> new NoSuchElementException("no filter wheel: " + id));
    }
}
```

`src/main/java/dev/nocs/device/api/FocuserController.java`:

```java
package dev.nocs.device.api;

import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceService;
import dev.nocs.device.Focuser;
import dev.nocs.device.api.dto.MoveRequest;
import java.util.NoSuchElementException;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/focusers/{id}")
public class FocuserController {

    private final DeviceService service;
    public FocuserController(DeviceService service) { this.service = service; }

    @PostMapping("/move")
    public void move(@PathVariable String id, @RequestBody MoveRequest req) {
        if (req.position() != null) focuser(id).moveAbsolute(req.position());
        else if (req.offset() != null) focuser(id).moveRelative(req.offset());
        else throw new IllegalArgumentException("supply either position or offset");
    }

    private Focuser focuser(String id) {
        return service.registry().focuser(new DeviceId(id))
                .orElseThrow(() -> new NoSuchElementException("no focuser: " + id));
    }
}
```

- [ ] **Step 12.7: Spring wiring — `@Bean`s in `AppConfig`**

Create (or extend) `src/main/java/dev/nocs/config/AppConfig.java`:

```java
package dev.nocs.config;

import dev.nocs.device.CameraImageSink;
import dev.nocs.device.DeviceService;
import dev.nocs.device.TempDirCameraImageSink;
import dev.nocs.events.EventBus;
import dev.nocs.indi.IndiClient;
import dev.nocs.indi.IndiConfig;
import dev.nocs.indi.IndiServerSupervisor;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import java.io.IOException;
import java.nio.file.Path;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class AppConfig {

    @Bean
    IndiClient indiClient() { return new IndiClient(); }

    @Bean
    CameraImageSink cameraImageSink(NocsProperties props, EventBus bus,
                                    @Value("${nocs.data-dir:${java.io.tmpdir}/nocs}") String dataDir) {
        return new TempDirCameraImageSink(Path.of(dataDir), bus);
    }

    @Bean
    DeviceService deviceService(IndiClient client, EventBus bus, CameraImageSink sink) {
        return new DeviceService(client, bus, sink);
    }

    @Bean
    IndiServerSupervisor indiServerSupervisor(NocsProperties props, EventBus bus) {
        IndiConfig cfg = props.indi() != null ? props.indi()
                : new IndiConfig(IndiConfig.Mode.DISABLED, "127.0.0.1", 7624, java.util.List.of(), null);
        return new IndiServerSupervisor(cfg, bus);
    }

    @Bean
    IndiLifecycle indiLifecycle(NocsProperties props, IndiServerSupervisor sup, IndiClient client) {
        return new IndiLifecycle(props, sup, client);
    }

    public static class IndiLifecycle {
        private final NocsProperties props;
        private final IndiServerSupervisor sup;
        private final IndiClient client;

        public IndiLifecycle(NocsProperties props, IndiServerSupervisor sup, IndiClient client) {
            this.props = props;
            this.sup = sup;
            this.client = client;
        }

        @PostConstruct
        public void start() throws IOException, InterruptedException {
            if (props.indi() == null || props.indi().mode() == IndiConfig.Mode.DISABLED) return;
            if (props.indi().mode() == IndiConfig.Mode.MANAGED) {
                sup.start();
                Thread.sleep(1000);
            }
            client.connect(props.indi().host(), props.indi().port());
        }

        @PreDestroy
        public void stop() {
            try { client.close(); } catch (Exception ignored) {}
            sup.stop();
        }
    }
}
```

- [ ] **Step 12.8: Failing tests for kind-specific controllers**

Create `src/test/java/dev/nocs/device/api/MountControllerTest.java`:

```java
package dev.nocs.device.api;

import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceRegistry;
import dev.nocs.device.DeviceService;
import dev.nocs.device.Mount;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(properties = "nocs.auth.token=t")
class MountControllerTest {

    @Autowired MockMvc mvc;
    @MockitoBean DeviceService service;

    private final Mount mount = mock(Mount.class);

    @BeforeEach
    void setup() {
        DeviceRegistry reg = mock(DeviceRegistry.class);
        when(service.registry()).thenReturn(reg);
        when(reg.mount(new DeviceId("telescope-simulator"))).thenReturn(java.util.Optional.of(mount));
    }

    @Test
    void slew() throws Exception {
        mvc.perform(post("/api/mounts/telescope-simulator/slew")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"raHours\":0.71,\"decDegrees\":41.27}"))
                .andExpect(status().isOk());
        verify(mount).slew(0.71, 41.27);
    }

    @Test
    void park() throws Exception {
        mvc.perform(post("/api/mounts/telescope-simulator/park").header("Authorization", "Bearer t"))
                .andExpect(status().isOk());
        verify(mount).park();
    }

    @Test
    void sync() throws Exception {
        mvc.perform(post("/api/mounts/telescope-simulator/sync")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"raHours\":1.0,\"decDegrees\":2.0}"))
                .andExpect(status().isOk());
        verify(mount).syncTo(1.0, 2.0);
    }
}
```

Create `src/test/java/dev/nocs/device/api/CameraControllerTest.java`:

```java
package dev.nocs.device.api;

import dev.nocs.device.Camera;
import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceRegistry;
import dev.nocs.device.DeviceService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(properties = "nocs.auth.token=t")
class CameraControllerTest {

    @Autowired MockMvc mvc;
    @MockitoBean DeviceService service;
    private final Camera camera = mock(Camera.class);

    @BeforeEach
    void setup() {
        DeviceRegistry reg = mock(DeviceRegistry.class);
        when(service.registry()).thenReturn(reg);
        when(reg.camera(new DeviceId("ccd-simulator"))).thenReturn(java.util.Optional.of(camera));
    }

    @Test
    void expose() throws Exception {
        mvc.perform(post("/api/cameras/ccd-simulator/expose")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"durationSeconds\":3.0}"))
                .andExpect(status().isOk());
        verify(camera).expose(3.0);
    }

    @Test
    void cool() throws Exception {
        mvc.perform(post("/api/cameras/ccd-simulator/cool")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"setpointCelsius\":-15.0}"))
                .andExpect(status().isOk());
        verify(camera).cool(-15.0);
    }
}
```

Create `src/test/java/dev/nocs/device/api/FilterWheelControllerTest.java`:

```java
package dev.nocs.device.api;

import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceRegistry;
import dev.nocs.device.DeviceService;
import dev.nocs.device.FilterWheel;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(properties = "nocs.auth.token=t")
class FilterWheelControllerTest {

    @Autowired MockMvc mvc;
    @MockitoBean DeviceService service;
    private final FilterWheel wheel = mock(FilterWheel.class);

    @BeforeEach
    void setup() {
        DeviceRegistry reg = mock(DeviceRegistry.class);
        when(service.registry()).thenReturn(reg);
        when(reg.filterWheel(new DeviceId("filter-simulator"))).thenReturn(java.util.Optional.of(wheel));
    }

    @Test
    void select() throws Exception {
        mvc.perform(post("/api/filterwheels/filter-simulator/select")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"slot\":3}"))
                .andExpect(status().isOk());
        verify(wheel).selectSlot(3);
    }
}
```

Create `src/test/java/dev/nocs/device/api/FocuserControllerTest.java`:

```java
package dev.nocs.device.api;

import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceRegistry;
import dev.nocs.device.DeviceService;
import dev.nocs.device.Focuser;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(properties = "nocs.auth.token=t")
class FocuserControllerTest {

    @Autowired MockMvc mvc;
    @MockitoBean DeviceService service;
    private final Focuser focuser = mock(Focuser.class);

    @BeforeEach
    void setup() {
        DeviceRegistry reg = mock(DeviceRegistry.class);
        when(service.registry()).thenReturn(reg);
        when(reg.focuser(new DeviceId("focuser-simulator"))).thenReturn(java.util.Optional.of(focuser));
    }

    @Test
    void moveAbsolute() throws Exception {
        mvc.perform(post("/api/focusers/focuser-simulator/move")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"position\":12500}"))
                .andExpect(status().isOk());
        verify(focuser).moveAbsolute(12500);
    }

    @Test
    void moveRelative() throws Exception {
        mvc.perform(post("/api/focusers/focuser-simulator/move")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"offset\":-200}"))
                .andExpect(status().isOk());
        verify(focuser).moveRelative(-200);
    }
}
```

- [ ] **Step 12.9: Run — expect pass**

Run: `./gradlew test --tests 'dev.nocs.device.api.*'`
Expected: all tests in the five controller test classes pass.

Run the full suite: `./gradlew test`
Expected: everything green, including Plan A's existing tests. If `IndiLifecycle` tries to connect during a `@SpringBootTest` that doesn't expect it, `nocs.indi.mode=disabled` default in `application.yaml` keeps it quiet.

- [ ] **Step 12.10: Commit**

```bash
git add src/main/java/dev/nocs/device/ \
        src/main/java/dev/nocs/config/AppConfig.java \
        src/test/java/dev/nocs/device/api/
git commit -m "feat: DeviceService, registry, REST controllers, Spring wiring"
```

---

### Task 13: End-to-end simulator integration test

**Files:**
- Create: `src/test/java/dev/nocs/device/IndiSimulatorIntegrationTest.java`

This test is the demoable milestone: real `indiserver` + real simulator drivers + real HTTP → real state transitions → real BLOB in the sink.

Gating: the test is `@EnabledIfEnvironmentVariable(named = "NOCS_INDI_BIN", matches = "1")`. Locally run with `NOCS_INDI_BIN=1 ./gradlew test --tests '*IndiSimulatorIntegrationTest'`. CI sets `NOCS_INDI_BIN=1` after installing `indi-bin` (Task 14).

- [ ] **Step 13.1: Write the test**

Create `src/test/java/dev/nocs/device/IndiSimulatorIntegrationTest.java`:

```java
package dev.nocs.device;

import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import java.net.ServerSocket;
import java.time.Duration;
import java.util.EnumSet;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.condition.EnabledOnOs;
import org.junit.jupiter.api.condition.OS;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest
@AutoConfigureMockMvc
@EnabledIfEnvironmentVariable(named = "NOCS_INDI_BIN", matches = "1")
@EnabledOnOs(OS.LINUX)
class IndiSimulatorIntegrationTest {

    private static final int PORT = pickPort();

    @DynamicPropertySource
    static void indiProps(DynamicPropertyRegistry reg) {
        reg.add("nocs.auth.token", () -> "t");
        reg.add("nocs.indi.mode", () -> "managed");
        reg.add("nocs.indi.host", () -> "127.0.0.1");
        reg.add("nocs.indi.port", () -> Integer.toString(PORT));
        reg.add("nocs.indi.drivers[0]", () -> "indi_simulator_telescope");
        reg.add("nocs.indi.drivers[1]", () -> "indi_simulator_ccd");
        reg.add("nocs.indi.drivers[2]", () -> "indi_simulator_focus");
        reg.add("nocs.indi.drivers[3]", () -> "indi_simulator_wheel");
    }

    @Autowired MockMvc mvc;
    @Autowired EventBus bus;

    @Test
    void endToEndSequence() throws Exception {
        CopyOnWriteArrayList<Event> seen = new CopyOnWriteArrayList<>();
        var sub = bus.subscribe(EnumSet.allOf(Topic.class)).subscribe(seen::add);

        // 1. Devices appear.
        Awaitility.await().atMost(Duration.ofSeconds(30)).untilAsserted(() ->
                mvc.perform(get("/api/devices").header("Authorization", "Bearer t"))
                        .andExpect(status().isOk())
                        .andExpect(jsonPath("$[?(@.kind=='mount')].id").isNotEmpty())
                        .andExpect(jsonPath("$[?(@.kind=='camera')].id").isNotEmpty())
                        .andExpect(jsonPath("$[?(@.kind=='focuser')].id").isNotEmpty())
                        .andExpect(jsonPath("$[?(@.kind=='filterwheel')].id").isNotEmpty()));

        // 2. Connect all devices.
        for (String id : deviceIds()) {
            mvc.perform(post("/api/devices/" + id + "/connect").header("Authorization", "Bearer t"))
                    .andExpect(status().isOk());
        }

        // 3. Slew mount, expose camera, select filter slot, move focuser.
        mvc.perform(post("/api/mounts/telescope-simulator/slew")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"raHours\":0.712,\"decDegrees\":41.269}"))
                .andExpect(status().isOk());

        mvc.perform(post("/api/cameras/ccd-simulator/expose")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"durationSeconds\":1.0}"))
                .andExpect(status().isOk());

        mvc.perform(post("/api/filterwheels/filter-simulator/select")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"slot\":2}"))
                .andExpect(status().isOk());

        mvc.perform(post("/api/focusers/focuser-simulator/move")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"position\":20000}"))
                .andExpect(status().isOk());

        // 4. Verify events eventually arrive.
        Awaitility.await().atMost(Duration.ofSeconds(30)).untilAsserted(() -> {
            long mountStates = seen.stream().filter(e -> e.topic() == Topic.MOUNT).count();
            long cameraImages = seen.stream()
                    .filter(e -> e.topic() == Topic.CAMERA && "image_received".equals(e.type())).count();
            long wheelStates = seen.stream().filter(e -> e.topic() == Topic.FILTERWHEEL).count();
            long focuserStates = seen.stream().filter(e -> e.topic() == Topic.FOCUSER).count();
            org.assertj.core.api.Assertions.assertThat(mountStates).isGreaterThanOrEqualTo(1);
            org.assertj.core.api.Assertions.assertThat(cameraImages).isGreaterThanOrEqualTo(1);
            org.assertj.core.api.Assertions.assertThat(wheelStates).isGreaterThanOrEqualTo(1);
            org.assertj.core.api.Assertions.assertThat(focuserStates).isGreaterThanOrEqualTo(1);
        });

        sub.dispose();
    }

    private List<String> deviceIds() {
        return List.of("telescope-simulator", "ccd-simulator", "focuser-simulator", "filter-simulator");
    }

    private static int pickPort() {
        try (ServerSocket s = new ServerSocket(0)) { return s.getLocalPort(); }
        catch (Exception e) { throw new RuntimeException(e); }
    }
}
```

Device IDs may vary slightly across `indi-bin` versions (e.g. "CCD Simulator" → `ccd-simulator`, but the exact slugs `telescope-simulator`, `ccd-simulator`, `focuser-simulator`, `filter-simulator` correspond to the driver names listed above). If a slug differs on the CI runner, update the `deviceIds()` list after an initial CI run reveals the actual names.

- [ ] **Step 13.2: Run locally**

Prerequisites: `sudo apt-get install -y indi-bin` (Debian/Ubuntu). Verify with `which indiserver indi_simulator_telescope`.

Run: `NOCS_INDI_BIN=1 ./gradlew test --tests 'dev.nocs.device.IndiSimulatorIntegrationTest' -i`
Expected: the test passes in < 60 s. If it times out, inspect `./gradlew`'s output for `[indiserver]` lines; if a driver is missing, install it (`indi-bin` ships all four simulators on Debian 12+).

- [ ] **Step 13.3: Commit**

```bash
git add src/test/java/dev/nocs/device/IndiSimulatorIntegrationTest.java
git commit -m "test: end-to-end simulator integration test for all four device kinds"
```

---

### Task 14: CI — install `indi-bin`, enable integration test

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 14.1: Update the CI workflow**

Replace the `Run tests` step, and add an "Install INDI" step before it:

```yaml
      - name: Install INDI
        run: |
          sudo apt-get update
          sudo apt-get install -y indi-bin
          which indiserver indi_simulator_telescope indi_simulator_ccd indi_simulator_focus indi_simulator_wheel

      - name: Run tests
        env:
          NOCS_INDI_BIN: "1"
        run: ./gradlew --no-daemon check
```

The rest of `ci.yml` (archive build + smoke test + artifact upload) stays unchanged.

- [ ] **Step 14.2: Verify locally the tests still pass in the same environment**

```bash
NOCS_INDI_BIN=1 ./gradlew --no-daemon check
```

Expected: `BUILD SUCCESSFUL`, including the new integration test.

- [ ] **Step 14.3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: install indi-bin and enable INDI simulator integration test"
```

---

### Task 15: README + final verification

**Files:**
- Modify: `README.md`

- [ ] **Step 15.1: Add a "Devices & INDI" section to `README.md`**

Insert below the existing "Developer quickstart" section:

```markdown
## Devices & INDI

NOCS uses INDI as its driver backplane. When `nocs.indi.mode=managed` NOCS launches `indiserver` with the configured drivers; when `mode=external` it connects to an already-running `indiserver` on the configured host/port; `mode=disabled` skips devices entirely (useful for the v0.1 skeleton and headless smoke tests).

The default `config.yaml` points at four INDI simulator drivers:

- `indi_simulator_telescope` (mount)
- `indi_simulator_ccd` (camera, produces a fake FITS on each exposure)
- `indi_simulator_focus` (focuser)
- `indi_simulator_wheel` (filter wheel)

Install `indi-bin` (Debian/Ubuntu: `sudo apt-get install -y indi-bin`) so those binaries are on `PATH`, then:

```bash
TOKEN="<printed token>"
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/devices
curl -s -X POST -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/devices/telescope-simulator/connect
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"raHours":0.712,"decDegrees":41.269}' http://localhost:8080/api/mounts/telescope-simulator/slew
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"durationSeconds":1.0}' http://localhost:8080/api/cameras/ccd-simulator/expose
```

Captured FITS bytes are written to `data_dir/captures/tmp/<ts>-<n>.fits` until Plan D replaces the temp-dir sink with a real `ImageStoreService`.
```

- [ ] **Step 15.2: Full clean build**

```bash
NOCS_INDI_BIN=1 ./gradlew clean check distTar
./smoke/smoke.sh build/distributions/nocs-0.1.0-SNAPSHOT-linux-x86_64.tar.gz
```

Expected: everything green. (The jlink `distTar` archive does not itself require `indi-bin` — it contains NOCS only.)

- [ ] **Step 15.3: Update decomposition doc status**

Open `docs/superpowers/plans/2026-04-22-v0.1-plan-decomposition.md` and change the Plan B status row to:

```markdown
| B | Yes | [2026-04-22-nocs-device-layer-and-indi.md](./2026-04-22-nocs-device-layer-and-indi.md) |
```

- [ ] **Step 15.4: Commit**

```bash
git add README.md docs/superpowers/plans/2026-04-22-v0.1-plan-decomposition.md
git commit -m "docs: device layer + INDI section in README; mark Plan B written"
```

---

## Self-Review Notes

**Spec coverage (relative to `docs/superpowers/specs/2026-04-21-nocs-v0.1-design.md`):**

- §4.1/§4.3 abstract device layer — Tasks 6, 7–11.
- §5.1/§5.2 INDI as driver backplane — whole plan, specifically Task 5 (supervisor) + Tasks 3–4 (client).
- §5.3 architecture allows future adapters — interfaces in Task 6 live on their own; `IndiDeviceFactory` is one producer among possible many.
- §5.4 INDI client scope (pure Java, no JNI; properties, switch/number/text, BLOB) — Tasks 2–4.
- §6.4 state machines — Task 6 enums, Tasks 8–11 transitions.
- §8.2 device REST API — Task 12.
- §8.3 event topics `mount`, `camera`, `filterwheel`, `focuser`, `device_connection`, `system` — already enumerated in Plan A; published by Tasks 5, 8–12.
- §14.2 NOCS supervises `indiserver`; logs propagated — Task 5.
- §17 simulator-based integration tests — Tasks 13, 14.

Deliberately **not** covered (belongs to later plans):
- Autofocus routine / `POST /api/focusers/{id}/autofocus` — Plan G.
- `ImageStoreService` with FITS canonical layout, thumbnails, and `/api/images/*` — Plan D.
- Target / sequence / safety / plate-solver integrations — Plans C/E/F/G.

**Type/name consistency check:**

- `IndiProperty` sealed hierarchy: `SwitchVector`, `NumberVector`, `TextVector`, `BlobVector` — identical in codec, client, adapters, tests.
- `IndiClient` public surface: `connect(host, port)`, `close()`, `updates()`, `properties(device)`, `property(device, name)`, `devices()`, `setSwitch`, `setNumber`, `setText`, `enableBlob`, `onBlob(BlobCallback)`.
- `Device` interface methods: `id()`, `indiName()`, `kind()`, `isConnected()`, `connect()`, `disconnect()`.
- `Mount` methods: `slew(raHours, decDegrees)`, `syncTo(raHours, decDegrees)`, `park()`, `unpark()`, `abort()`, `state()` — same in interface, adapter, controller, tests.
- `Camera` methods: `cool(setpointCelsius)`, `expose(durationSeconds)`, `abortExposure()`, `state()`, `currentTemperatureCelsius()`.
- `FilterWheel` methods: `selectSlot(int)`, `slotNames()`, `currentSlot()`, `state()`.
- `Focuser` methods: `moveAbsolute(int)`, `moveRelative(int)`, `currentPosition()`, `abort()`, `state()`.
- `CameraImageSink.accept(DeviceId, byte[], String)` — single definition; called from `IndiCameraAdapter.onBlob(...)` and `TempDirCameraImageSink`.
- Device IDs used in REST: the slug of the INDI device name (e.g. `"telescope-simulator"`, `"ccd-simulator"`, `"filter-simulator"`, `"focuser-simulator"`). Every controller test uses the same slugs; integration test lists them in `deviceIds()`.
- Config keys under `nocs.indi.*`: `mode`, `host`, `port`, `drivers`, `restart.initial-backoff-ms`, `restart.max-backoff-ms`. All tests and `config.example.yaml` agree.
- INDI property names used by adapters match the simulator driver naming (`CONNECTION`, `EQUATORIAL_EOD_COORD`, `ON_COORD_SET`, `TELESCOPE_PARK`, `TELESCOPE_ABORT_MOTION`, `CCD_EXPOSURE`, `CCD_TEMPERATURE`, `CCD_COOLER`, `CCD_ABORT_EXPOSURE`, `CCD1`, `UPLOAD_MODE`, `FILTER_SLOT`, `FILTER_NAME`, `ABS_FOCUS_POSITION`, `FOCUS_ABORT_MOTION`).

**No placeholders:** every step has full code, exact commands, and expected outcomes. The only soft note is "device slugs may vary by `indi-bin` version" in Task 13.1 — the fix is mechanical (edit the list).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-22-nocs-device-layer-and-indi.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
