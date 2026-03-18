package dev.nocs.api;

import dev.nocs.domain.EquipmentType;
import dev.nocs.domain.LogicalDevice;
import dev.nocs.service.DriverRegistry;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(DeviceController.class)
class DeviceControllerTest {

    @Autowired
    MockMvc mockMvc;

    @MockBean
    DriverRegistry driverRegistry;

    @Test
    void listDevices_returnsGroupedByType() throws Exception {
        LogicalDevice cam = new LogicalDevice("Cam", "03c3:120e", EquipmentType.CAMERA, 0);
        when(driverRegistry.listDevicesGroupedByType())
                .thenReturn(Map.of(EquipmentType.CAMERA, List.of(cam)));

        mockMvc.perform(get("/devices"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.CAMERA").isArray())
                .andExpect(jsonPath("$.CAMERA[0].displayName").value("Cam"))
                .andExpect(jsonPath("$.CAMERA[0].hardwareId").value("03c3:120e"))
                .andExpect(jsonPath("$.CAMERA[0].equipmentType").value("CAMERA"))
                .andExpect(jsonPath("$.CAMERA[0].index").value(0));
    }

    @Test
    void listDevicesByType_returnsDevicesForType() throws Exception {
        LogicalDevice cam = new LogicalDevice("Cam", "03c3:120e", EquipmentType.CAMERA, 0);
        when(driverRegistry.listDevices(EquipmentType.CAMERA)).thenReturn(List.of(cam));

        mockMvc.perform(get("/devices/CAMERA"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$").isArray())
                .andExpect(jsonPath("$[0].displayName").value("Cam"));
    }

    @Test
    void listDevicesByType_returns400ForInvalidType() throws Exception {
        mockMvc.perform(get("/devices/INVALID"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void getDevice_returnsDeviceWhenFound() throws Exception {
        LogicalDevice device = new LogicalDevice("Cam", "03c3:120e", EquipmentType.CAMERA, 0);
        when(driverRegistry.getDevice(EquipmentType.CAMERA, "03c3:120e", 0))
                .thenReturn(Optional.of(device));

        mockMvc.perform(get("/devices/CAMERA/03c3-120e/0"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.displayName").value("Cam"))
                .andExpect(jsonPath("$.hardwareId").value("03c3:120e"))
                .andExpect(jsonPath("$.index").value(0));
    }

    @Test
    void getDevice_returns404WhenNotFound() throws Exception {
        when(driverRegistry.getDevice(EquipmentType.CAMERA, "03c3:120e", 0))
                .thenReturn(Optional.empty());

        mockMvc.perform(get("/devices/CAMERA/03c3-120e/0"))
                .andExpect(status().isNotFound());
    }

    @Test
    void getDevice_returns400ForInvalidEquipmentType() throws Exception {
        mockMvc.perform(get("/devices/BAD/03c3-120e/0"))
                .andExpect(status().isBadRequest());
    }
}
