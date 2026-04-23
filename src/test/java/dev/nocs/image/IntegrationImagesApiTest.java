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

    @Autowired
    CameraImageSink sink;
    @Autowired
    SessionService sessions;
    @Autowired
    ObjectMapper json;
    @LocalServerPort
    int port;
    @MockBean
    DeviceService deviceService;

    @Test
    void exposeThenDownloadRoundTrip() throws Exception {
        DeviceId cam = new DeviceId("ccd-int");
        DeviceRegistry registry = new DeviceRegistry();
        registry.add(new StubCamera(cam));
        when(deviceService.registry()).thenReturn(registry);

        sessions.open("integration");

        HttpClient http = HttpClient.newHttpClient();

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

        short[] pixels = new short[16 * 16];
        for (int i = 0; i < pixels.length; i++) {
            pixels[i] = (short) (i * 50 - 32768);
        }
        byte[] fits = MiniFits.build16(16, 16, pixels, Map.of(
                "DATE-OBS", "'2026-04-22T22:45:00'"));
        sink.accept(cam, fits, ".fits");

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
                        HttpResponse.BodyHandlers.ofString())
                .body()).get(0).get("id").asLong();

        HttpResponse<byte[]> fitsResp = http.send(
                HttpRequest.newBuilder(URI.create(base() + "/api/images/" + id + ".fits"))
                        .header("Authorization", "Bearer t").GET().build(),
                HttpResponse.BodyHandlers.ofByteArray());
        assertThat(fitsResp.statusCode()).isEqualTo(200);
        assertThat(fitsResp.body()).isEqualTo(fits);

        HttpResponse<byte[]> thumbResp = http.send(
                HttpRequest.newBuilder(URI.create(base() + "/api/images/" + id + "/thumb.jpg"))
                        .header("Authorization", "Bearer t").GET().build(),
                HttpResponse.BodyHandlers.ofByteArray());
        assertThat(thumbResp.statusCode()).isEqualTo(200);
        assertThat(thumbResp.body().length).isGreaterThan(100);

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

        StubCamera(DeviceId id) {
            this.id = id;
        }

        @Override
        public DeviceId id() {
            return id;
        }

        @Override
        public String indiName() {
            return id.value();
        }

        @Override
        public DeviceKind kind() {
            return DeviceKind.CAMERA;
        }

        @Override
        public boolean isConnected() {
            return true;
        }

        @Override
        public void connect() {}

        @Override
        public void disconnect() {}

        @Override
        public CameraState state() {
            return CameraState.IDLE;
        }

        @Override
        public void cool(double setpointCelsius) {}

        @Override
        public void expose(double durationSeconds) {}

        @Override
        public void abortExposure() {}

        @Override
        public Double currentTemperatureCelsius() {
            return null;
        }
    }
}
