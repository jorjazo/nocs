package dev.nocs.device.api;

import dev.nocs.device.Camera;
import dev.nocs.device.CameraState;
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
import static org.mockito.Mockito.clearInvocations;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(properties = "nocs.auth.token=t")
class CameraControllerExposeMetadataTest {

    @Autowired
    MockMvc mvc;
    @MockBean
    DeviceService deviceService;
    @SpyBean
    ImageStoreService imageStore;

    private Camera camera;

    @BeforeEach
    void setUp() {
        clearInvocations(imageStore);
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
        verify(imageStore).prepareCapture(eq(new DeviceId("ccd-x")), ctxCap.capture());

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
        public void expose(double durationSeconds) {
            exposeCalls++;
        }

        @Override
        public void abortExposure() {}

        @Override
        public Double currentTemperatureCelsius() {
            return null;
        }
    }
}
