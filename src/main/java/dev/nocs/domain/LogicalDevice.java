package dev.nocs.domain;

/**
 * A logical device exposed by a driver. One driver can provide multiple logical devices
 * (e.g. two cameras, or filter wheel + focuser). Extends HardwareDevice with an index.
 */
public record LogicalDevice(
        String displayName,
        String vendorId,
        String productId,
        EquipmentType equipmentType,
        int index
) {
    public LogicalDevice {
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
        if (index < 0) {
            throw new IllegalArgumentException("index must be >= 0");
        }
    }
}
