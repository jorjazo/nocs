package dev.nocs.api;

import dev.nocs.domain.Driver;
import dev.nocs.service.DriverRegistry;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;
import java.util.Optional;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(DriverController.class)
class DriverControllerTest {

    @Autowired
    MockMvc mockMvc;

    @MockBean
    DriverRegistry driverRegistry;

    @Test
    void listDrivers_returnsAllDrivers() throws Exception {
        Driver driver = new Driver("driver.id", "Test Driver", "Desc", "1.0", "Mfr", "https://x.com", List.of());
        when(driverRegistry.listDrivers()).thenReturn(List.of(driver));

        mockMvc.perform(get("/drivers"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$").isArray())
                .andExpect(jsonPath("$[0].id").value("driver.id"))
                .andExpect(jsonPath("$[0].displayName").value("Test Driver"));
    }

    @Test
    void getDriver_returnsDriverWhenFound() throws Exception {
        Driver driver = new Driver("driver.id", "Test Driver", "Desc", "1.0", "Mfr", "https://x.com", List.of());
        when(driverRegistry.getDriver("driver.id")).thenReturn(Optional.of(driver));

        mockMvc.perform(get("/drivers/driver.id"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value("driver.id"))
                .andExpect(jsonPath("$.displayName").value("Test Driver"));
    }

    @Test
    void getDriver_returns404WhenNotFound() throws Exception {
        when(driverRegistry.getDriver("nonexistent")).thenReturn(Optional.empty());

        mockMvc.perform(get("/drivers/nonexistent"))
                .andExpect(status().isNotFound());
    }
}
