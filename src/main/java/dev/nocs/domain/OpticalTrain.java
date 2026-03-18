package dev.nocs.domain;

import java.util.Optional;

/**
 * A first-class optical train defining a telescope/camera setup. Can be shared
 * across profiles. Contains focal length, aperture, and optional camera,
 * focuser, and filter wheel.
 */
public record OpticalTrain(
        String id,
        String name,
        double focalLengthMm,
        Double apertureMm,
        DeviceReference camera,
        DeviceReference focuser,
        DeviceReference filterWheel
) {
    public OpticalTrain {
        if (id == null || id.isBlank()) {
            throw new IllegalArgumentException("id must not be blank");
        }
        if (name == null || name.isBlank()) {
            throw new IllegalArgumentException("name must not be blank");
        }
        if (focalLengthMm <= 0) {
            throw new IllegalArgumentException("focalLengthMm must be positive");
        }
        if (apertureMm != null && apertureMm <= 0) {
            throw new IllegalArgumentException("apertureMm must be positive when present");
        }
    }

    public Optional<Double> apertureOpt() {
        return Optional.ofNullable(apertureMm);
    }

    public Optional<DeviceReference> cameraOpt() {
        return Optional.ofNullable(camera);
    }

    public Optional<DeviceReference> focuserOpt() {
        return Optional.ofNullable(focuser);
    }

    public Optional<DeviceReference> filterWheelOpt() {
        return Optional.ofNullable(filterWheel);
    }
}
