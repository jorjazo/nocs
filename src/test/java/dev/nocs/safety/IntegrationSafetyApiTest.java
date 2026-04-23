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
import static org.hamcrest.Matchers.hasItem;
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
        Files.writeString(
                rules,
                """
                rules:
                  - name: rain
                    when: { rain_detected: true }
                    then: e_stop
                """);
        reg.add("nocs.auth.token", () -> "t");
        reg.add("nocs.safety.rules-path", () -> rules.toString());
    }

    @Autowired
    MockMvc mvc;
    @Autowired
    DeviceService deviceService;
    @Autowired
    EventBus bus;
    @Autowired
    SafetyService safety;

    private FakeMount mount;
    private FakeCamera camera;
    private Disposable sub;
    private final CopyOnWriteArrayList<Event> seen = new CopyOnWriteArrayList<>();

    @BeforeEach
    void setUp() {
        safety.reload();
        safety.reset("test-setup");

        mount = new FakeMount();
        camera = new FakeCamera();
        deviceService.registry().add(mount);
        deviceService.registry().add(camera);
        mount.connect();
        camera.connect();

        sub = bus.subscribeAll().subscribe(seen::add);
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

            assertThat(seen.stream()
                            .filter(e -> e.topic() == Topic.SAFETY && "rule_triggered".equals(e.type()))
                            .count())
                    .isEqualTo(1);
            assertThat(seen.stream()
                            .filter(e -> e.topic() == Topic.SAFETY && "e_stopped".equals(e.type()))
                            .count())
                    .isEqualTo(1);
            assertThat(seen.stream()
                            .filter(e -> e.topic() == Topic.SEQUENCE && "abort_requested".equals(e.type()))
                            .count())
                    .isEqualTo(1);
        });

        mvc.perform(get("/api/safety/rules").header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.rules[0].name").value("rain"))
                .andExpect(jsonPath("$.rules[0].latched").value(true))
                .andExpect(jsonPath("$.latched", hasItem("rain")));

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

        @Override
        public DeviceId id() {
            return new DeviceId("itest-mount");
        }

        @Override
        public String indiName() {
            return "ITestMount";
        }

        @Override
        public DeviceKind kind() {
            return DeviceKind.MOUNT;
        }

        @Override
        public boolean isConnected() {
            return state != MountState.DISCONNECTED;
        }

        @Override
        public void connect() {
            state = MountState.IDLE;
        }

        @Override
        public void disconnect() {
            state = MountState.DISCONNECTED;
        }

        @Override
        public MountState state() {
            return state;
        }

        @Override
        public void slew(double r, double d) {}

        @Override
        public void syncTo(double r, double d) {}

        @Override
        public void park() {
            parked++;
        }

        @Override
        public void unpark() {}

        @Override
        public void abort() {}

        @Override
        public void emergencyStop() {
            eStopped++;
            state = MountState.E_STOPPED;
        }

        @Override
        public void resetEStop() {
            if (state == MountState.E_STOPPED) {
                state = MountState.IDLE;
            }
        }
    }

    private static final class FakeCamera implements Camera {
        int aborted;
        int eStopped;
        private CameraState state = CameraState.DISCONNECTED;

        @Override
        public DeviceId id() {
            return new DeviceId("itest-camera");
        }

        @Override
        public String indiName() {
            return "ITestCcd";
        }

        @Override
        public DeviceKind kind() {
            return DeviceKind.CAMERA;
        }

        @Override
        public boolean isConnected() {
            return state != CameraState.DISCONNECTED;
        }

        @Override
        public void connect() {
            state = CameraState.IDLE;
        }

        @Override
        public void disconnect() {
            state = CameraState.DISCONNECTED;
        }

        @Override
        public CameraState state() {
            return state;
        }

        @Override
        public void cool(double s) {}

        @Override
        public void expose(double s) {}

        @Override
        public void abortExposure() {
            aborted++;
        }

        @Override
        public Double currentTemperatureCelsius() {
            return null;
        }

        @Override
        public void emergencyStop() {
            eStopped++;
            state = CameraState.E_STOPPED;
        }

        @Override
        public void resetEStop() {
            if (state == CameraState.E_STOPPED) {
                state = CameraState.IDLE;
            }
        }
    }
}
