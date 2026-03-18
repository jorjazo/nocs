package dev.nocs.domain;

/**
 * Represents a physical hardware device (e.g. USB device with vendorId/productId).
 */
public record HardwareDevice(
        String displayName,
        String vendorId,
        String productId,
        EquipmentType equipmentType
) {
    public HardwareDevice {
        if (displayName == null || displayName.isBlank()) {
            throw new IllegalArgumentException("displayName must not be blank");
        }
        if (vendorId == null || vendorId.isBlank()) {
            throw new IllegalArgumentException("vendorId must not be blank");
        }
        if (productId == null || productId.isBlank()) {
            throw new IllegalArgumentException("productId must not be blank");
        }
        if (equipmentType == null) {
            throw new IllegalArgumentException("equipmentType must not be null");
        }
    }
}
