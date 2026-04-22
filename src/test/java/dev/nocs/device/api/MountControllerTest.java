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
class MountControllerTest {

    @Autowired
    MockMvc mvc;

    @MockBean
    DeviceService service;

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
