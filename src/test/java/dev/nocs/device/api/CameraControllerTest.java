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
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(properties = "nocs.auth.token=t")
class CameraControllerTest {

    @Autowired
    MockMvc mvc;

    @MockBean
    DeviceService service;

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
