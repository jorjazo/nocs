package dev.nocs.domain;

import java.util.List;
import java.util.Optional;

/**
 * A profile groups drivers that are loaded together and references optical trains
 * for imaging and guiding. When a profile is loaded, all its drivers are loaded;
 * when unloaded, all its drivers are unloaded.
 *
 * <p>Optical trains are first-class entities referenced by ID. Different profiles
 * can share the same optical train. A profile has zero or more imaging train IDs
 * and zero or one guiding train ID.
 *
 * <p>Mount priority: When drivers offer more than one mount, the profile keeps
 * an ordered list; the system operates the highest-priority available mount.
 */
public record Profile(
        String id,
        String name,
        List<String> driverIds,
        List<String> imagingTrainIds,
        String guidingTrainId,
        List<DeviceReference> mountPriority
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
        if (imagingTrainIds == null) {
            imagingTrainIds = List.of();
        }
        if (mountPriority == null) {
            mountPriority = List.of();
        }
    }

    public Optional<String> guidingTrainIdOpt() {
        return Optional.ofNullable(guidingTrainId);
    }
}
