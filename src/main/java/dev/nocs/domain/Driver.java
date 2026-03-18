package dev.nocs.domain;

import java.util.List;

/**
 * Metadata for a driver. Drivers report their metadata and supported vendor IDs
 * at runtime.
 */
public record Driver(
        String id,
        String displayName,
        String description,
        String version,
        String manufacturer,
        String website,
        List<String> supportedVendorIds
) {
    public Driver {
        if (id == null || id.isBlank()) {
            throw new IllegalArgumentException("id must not be blank");
        }
        if (displayName == null || displayName.isBlank()) {
            throw new IllegalArgumentException("displayName must not be blank");
        }
        if (supportedVendorIds == null) {
            supportedVendorIds = List.of();
        }
    }
}
