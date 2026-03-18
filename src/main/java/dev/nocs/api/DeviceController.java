package dev.nocs.api;

import dev.nocs.domain.EquipmentType;
import dev.nocs.domain.LogicalDevice;
import dev.nocs.service.DriverRegistry;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

@Tag(name = "Devices", description = "Logical devices from loaded drivers")
@RestController
@RequestMapping("/devices")
public class DeviceController {

    private final DriverRegistry driverRegistry;

    public DeviceController(DriverRegistry driverRegistry) {
        this.driverRegistry = driverRegistry;
    }

    @Operation(summary = "List devices", description = "List all logical devices from loaded drivers, grouped by equipment type")
    @ApiResponse(responseCode = "200", description = "Devices grouped by MOUNT, CAMERA, FOCUSER, FILTER_WHEEL")
    @GetMapping
    public Map<EquipmentType, List<LogicalDevice>> listDevices() {
        return driverRegistry.listDevicesGroupedByType();
    }

    @Operation(summary = "List devices by type", description = "List logical devices for an equipment type (MOUNT, CAMERA, FOCUSER, FILTER_WHEEL)")
    @ApiResponse(responseCode = "200", description = "List of devices")
    @ApiResponse(responseCode = "400", description = "Invalid equipment type")
    @GetMapping("/{equipmentTypeId}")
    public ResponseEntity<List<LogicalDevice>> listDevicesByType(
            @PathVariable String equipmentTypeId) {
        EquipmentType type = parseEquipmentType(equipmentTypeId);
        if (type == null) {
            return ResponseEntity.badRequest().build();
        }
        return ResponseEntity.ok(driverRegistry.listDevices(type));
    }

    @Operation(summary = "Get device", description = "Get a logical device by equipment type, vendor id, product id, and index")
    @ApiResponse(responseCode = "200", description = "Device found")
    @ApiResponse(responseCode = "400", description = "Invalid equipment type")
    @ApiResponse(responseCode = "404", description = "Device not found")
    @GetMapping("/{equipmentTypeId}/{vendorId}/{productId}/{index}")
    public ResponseEntity<LogicalDevice> getDevice(
            @PathVariable String equipmentTypeId,
            @PathVariable String vendorId,
            @PathVariable String productId,
            @PathVariable int index) {
        EquipmentType type = parseEquipmentType(equipmentTypeId);
        if (type == null) {
            return ResponseEntity.badRequest().build();
        }
        return driverRegistry.getDevice(type, vendorId, productId, index)
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
