package dev.nocs.api;

import dev.nocs.domain.EquipmentType;
import dev.nocs.domain.LogicalDevice;
import dev.nocs.service.DriverRegistry;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * REST API for devices (Phase 0).
 */
@RestController
@RequestMapping("/devices")
public class DeviceController {

    private final DriverRegistry driverRegistry;

    public DeviceController(DriverRegistry driverRegistry) {
        this.driverRegistry = driverRegistry;
    }

    /**
     * List devices, grouped by equipment type.
     */
    @GetMapping
    public Map<EquipmentType, List<LogicalDevice>> listDevices() {
        return driverRegistry.listDevicesGroupedByType();
    }

    /**
     * List logical devices for an equipment type.
     */
    @GetMapping("/{equipmentTypeId}")
    public ResponseEntity<List<LogicalDevice>> listDevicesByType(
            @PathVariable String equipmentTypeId) {
        EquipmentType type = parseEquipmentType(equipmentTypeId);
        if (type == null) {
            return ResponseEntity.badRequest().build();
        }
        return ResponseEntity.ok(driverRegistry.listDevices(type));
    }

    /**
     * Get a logical device by equipment type, hardware id, and index.
     */
    @GetMapping("/{equipmentTypeId}/{hwId}/{index}")
    public ResponseEntity<LogicalDevice> getDevice(
            @PathVariable String equipmentTypeId,
            @PathVariable String hwId,
            @PathVariable int index) {
        EquipmentType type = parseEquipmentType(equipmentTypeId);
        if (type == null) {
            return ResponseEntity.badRequest().build();
        }
        String decodedHwId = hwId.replace('-', ':');
        return driverRegistry.getDevice(type, decodedHwId, index)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    private EquipmentType parseEquipmentType(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return EquipmentType.valueOf(value.toUpperCase().replace('-', '_'));
        } catch (IllegalArgumentException e) {
            return null;
        }
    }
}
