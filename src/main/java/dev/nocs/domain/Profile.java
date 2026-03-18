package dev.nocs.domain;

import java.util.List;
import java.util.Optional;

/**
 * A profile groups drivers that are loaded together and defines optical trains
 * for imaging and guiding. When a profile is loaded, all its drivers are loaded;
 * when unloaded, all its drivers are unloaded.
 *
 * <p>Optical trains: A profile can have zero or more imaging trains and zero or
 * one guiding train. Each camera can only be used by one optical train; focusers
 * and filter wheels can be shared.
 *
 * <p>Mount priority: When drivers offer more than one mount, the profile keeps
 * an ordered list; the system operates the highest-priority available mount.
 */
public record Profile(
        String id,
        String name,
        List<String> driverIds,
        List<OpticalTrain> imagingTrains,
        OpticalTrain guidingTrain,
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
        if (imagingTrains == null) {
            imagingTrains = List.of();
        }
        if (mountPriority == null) {
            mountPriority = List.of();
        }
    }

    public Optional<OpticalTrain> guidingTrainOpt() {
        return Optional.ofNullable(guidingTrain);
    }
}
