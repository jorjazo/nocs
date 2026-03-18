package dev.nocs.domain;

/**
 * Represents a physical hardware device (e.g. USB device with hardwareId).
 */
public record HardwareDevice(
        String displayName,
        String hardwareId,
        EquipmentType equipmentType
) {
    public HardwareDevice {
        if (displayName == null || displayName.isBlank()) {
            throw new IllegalArgumentException("displayName must not be blank");
        }
        if (hardwareId == null || hardwareId.isBlank()) {
            throw new IllegalArgumentException("hardwareId must not be blank");
        }
        if (equipmentType == null) {
            throw new IllegalArgumentException("equipmentType must not be null");
        }
    }
}
