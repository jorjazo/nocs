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
class FilterWheelControllerTest {

    @Autowired
    MockMvc mvc;

    @MockBean
    DeviceService service;

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
