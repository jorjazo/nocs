package dev.nocs.domain;

import java.util.List;

/**
 * Metadata and logical devices for a driver. Drivers report their metadata
 * and logical devices at runtime.
 */
public record Driver(
        String id,
        String displayName,
        String description,
        String version,
        String manufacturer,
        String website,
        List<LogicalDevice> supportedHardwareDevices
) {
    public Driver {
        if (id == null || id.isBlank()) {
            throw new IllegalArgumentException("id must not be blank");
        }
        if (displayName == null || displayName.isBlank()) {
            throw new IllegalArgumentException("displayName must not be blank");
        }
        if (supportedHardwareDevices == null) {
            supportedHardwareDevices = List.of();
        }
    }
}
