package dev.nocs.domain;

import java.util.List;

/**
 * A profile groups drivers that are loaded together. When a profile is loaded,
 * all its drivers are loaded; when unloaded, all its drivers are unloaded.
 */
public record Profile(
        String id,
        String name,
        List<String> driverIds
) {
    public Profile {
        if (id == null || id.isBlank()) {
            throw new IllegalArgumentException("id must not be blank");
        }
        if (name == null || name.isBlank()) {
            throw new IllegalArgumentException("name must not be blank");
        }
        if (driverIds == null) {
            driverIds = List.of();
        }
    }
}
