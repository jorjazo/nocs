package dev.nocs.device;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import java.net.ServerSocket;
import java.time.Duration;
import java.util.EnumSet;
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
import org.springframework.test.web.servlet.MvcResult;
import reactor.core.Disposable;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureMockMvc
@EnabledIfEnvironmentVariable(named = "NOCS_INDI_BIN", matches = "1")
@EnabledOnOs(OS.LINUX)
class IndiSimulatorIntegrationTest {

    private static final int PORT = pickPort();

    private final ObjectMapper mapper = new ObjectMapper();

    @DynamicPropertySource
    static void indiProps(DynamicPropertyRegistry reg) {
        reg.add("nocs.indi.auto-connect", () -> "true");
        reg.add("nocs.auth.token", () -> "t");
        reg.add("nocs.indi.mode", () -> "managed");
        reg.add("nocs.indi.host", () -> "127.0.0.1");
        reg.add("nocs.indi.port", () -> Integer.toString(PORT));
        reg.add("nocs.indi.startup-wait-ms", () -> "5000");
        reg.add("nocs.indi.drivers[0]", () -> "indi_simulator_telescope");
        reg.add("nocs.indi.drivers[1]", () -> "indi_simulator_ccd");
        reg.add("nocs.indi.drivers[2]", () -> "indi_simulator_focus");
        reg.add("nocs.indi.drivers[3]", () -> "indi_simulator_wheel");
    }

    @Autowired
    MockMvc mvc;

    @Autowired
    EventBus bus;

    @Test
    void endToEndSequence() throws Exception {
        CopyOnWriteArrayList<Event> seen = new CopyOnWriteArrayList<>();
        Disposable sub = bus.subscribe(EnumSet.allOf(Topic.class)).subscribe(seen::add);

        Awaitility.await().atMost(Duration.ofSeconds(45)).untilAsserted(() ->
                mvc.perform(get("/api/devices").header("Authorization", "Bearer t"))
                        .andExpect(status().isOk())
                        .andExpect(jsonPath("$[?(@.kind=='mount')].id").isNotEmpty())
                        .andExpect(jsonPath("$[?(@.kind=='camera')].id").isNotEmpty())
                        .andExpect(jsonPath("$[?(@.kind=='focuser')].id").isNotEmpty())
                        .andExpect(jsonPath("$[?(@.kind=='filterwheel')].id").isNotEmpty()));

        MvcResult listResult =
                mvc.perform(get("/api/devices").header("Authorization", "Bearer t")).andReturn();
        JsonNode arr = mapper.readTree(listResult.getResponse().getContentAsString());
        String mountId = null;
        String cameraId = null;
        String wheelId = null;
        String focuserId = null;
        for (JsonNode n : arr) {
            String kind = n.get("kind").asText();
            String id = n.get("id").asText();
            switch (kind) {
                case "mount" -> mountId = id;
                case "camera" -> cameraId = id;
                case "filterwheel" -> wheelId = id;
                case "focuser" -> focuserId = id;
                default -> {
                }
            }
        }
        assertThat(mountId).isNotNull();
        assertThat(cameraId).isNotNull();
        assertThat(wheelId).isNotNull();
        assertThat(focuserId).isNotNull();

        for (String id : java.util.List.of(mountId, cameraId, wheelId, focuserId)) {
            mvc.perform(post("/api/devices/" + id + "/connect").header("Authorization", "Bearer t"))
                    .andExpect(status().isOk());
        }

        mvc.perform(post("/api/mounts/" + mountId + "/slew")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"raHours\":0.712,\"decDegrees\":41.269}"))
                .andExpect(status().isOk());

        mvc.perform(post("/api/cameras/" + cameraId + "/expose")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"durationSeconds\":1.0}"))
                .andExpect(status().isOk());

        mvc.perform(post("/api/filterwheels/" + wheelId + "/select")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"slot\":2}"))
                .andExpect(status().isOk());

        mvc.perform(post("/api/focusers/" + focuserId + "/move")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"position\":20000}"))
                .andExpect(status().isOk());

        Awaitility.await().atMost(Duration.ofSeconds(45)).untilAsserted(() -> {
            long mountStates = seen.stream().filter(e -> e.topic() == Topic.MOUNT).count();
            long cameraImages =
                    seen.stream().filter(e -> e.topic() == Topic.CAMERA && "image_saved".equals(e.type()))
                            .count();
            long wheelStates = seen.stream().filter(e -> e.topic() == Topic.FILTERWHEEL).count();
            long focuserStates = seen.stream().filter(e -> e.topic() == Topic.FOCUSER).count();
            assertThat(mountStates).isGreaterThanOrEqualTo(1);
            assertThat(cameraImages).isGreaterThanOrEqualTo(1);
            assertThat(wheelStates).isGreaterThanOrEqualTo(1);
            assertThat(focuserStates).isGreaterThanOrEqualTo(1);
        });

        sub.dispose();
    }

    private static int pickPort() {
        try (ServerSocket s = new ServerSocket(0)) {
            return s.getLocalPort();
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }
}
