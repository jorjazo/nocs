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
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(properties = "nocs.auth.token=t")
class DeviceControllerTest {

    @Autowired
    MockMvc mvc;

    @MockBean
    DeviceService service;

    @BeforeEach
    void setup() {
        IndiMountAdapter m = org.mockito.Mockito.mock(IndiMountAdapter.class);
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
        org.mockito.Mockito.verify(service).connect(new DeviceId("telescope-simulator"));
    }

    @Test
    void disconnectInvokesService() throws Exception {
        mvc.perform(post("/api/devices/telescope-simulator/disconnect").header("Authorization", "Bearer t"))
                .andExpect(status().isOk());
        org.mockito.Mockito.verify(service).disconnect(new DeviceId("telescope-simulator"));
    }
}
