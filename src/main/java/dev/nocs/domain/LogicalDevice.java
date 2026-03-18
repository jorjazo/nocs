package dev.nocs.domain;

/**
 * A logical device exposed by a driver. One driver can provide multiple logical devices
 * (e.g. two cameras, or filter wheel + focuser). Extends HardwareDevice with an index.
 */
public record LogicalDevice(
        String displayName,
        String hardwareId,
        EquipmentType equipmentType,
        int index
) {
    public LogicalDevice {
        if (displayName == null || displayName.isBlank()) {
            throw new IllegalArgumentException("displayName must not be blank");
        }
        if (hardwareId == null || hardwareId.isBlank()) {
            throw new IllegalArgumentException("hardwareId must not be blank");
        }
        if (equipmentType == null) {
            throw new IllegalArgumentException("equipmentType must not be null");
        }
        if (index < 0) {
            throw new IllegalArgumentException("index must be >= 0");
        }
    }
}
