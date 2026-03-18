package dev.nocs.domain;

/**
 * Reference to a logical device. Used in optical trains and mount priority lists.
 * Stores the device identity so it can be kept even when the device is not
 * currently available (e.g. driver not loaded).
 */
public record DeviceReference(
        EquipmentType equipmentType,
        String vendorId,
        String productId,
        int index,
        String displayName
) {
    public DeviceReference {
        if (equipmentType == null) {
            throw new IllegalArgumentException("equipmentType must not be null");
        }
        if (vendorId == null || vendorId.isBlank()) {
            throw new IllegalArgumentException("vendorId must not be blank");
        }
        if (productId == null || productId.isBlank()) {
            throw new IllegalArgumentException("productId must not be blank");
        }
        if (index < 0) {
            throw new IllegalArgumentException("index must be >= 0");
        }
        if (displayName == null) {
            displayName = "";
        }
    }

    /**
     * Create a DeviceReference from a LogicalDevice.
     */
    public static DeviceReference from(LogicalDevice device) {
        return new DeviceReference(
                device.equipmentType(),
                device.vendorId(),
                device.productId(),
                device.index(),
                device.displayName()
        );
    }

    /**
     * Check if this reference matches the given logical device.
     */
    public boolean matches(LogicalDevice device) {
        return device != null
                && equipmentType == device.equipmentType()
                && vendorId.equals(device.vendorId())
                && productId.equals(device.productId())
                && index == device.index();
    }

    /**
     * Unique key for this device (for deduplication, e.g. camera uniqueness).
     */
    public String key() {
        return equipmentType.name() + ":" + vendorId + ":" + productId + ":" + index;
    }
}
