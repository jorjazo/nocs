package dev.nocs.domain;

import java.util.Optional;

/**
 * An optical train defines a telescope/camera setup: focal length, aperture,
 * and optional camera, focuser, and filter wheel. Used for imaging and guiding.
 */
public record OpticalTrain(
        double focalLengthMm,
        Double apertureMm,
        DeviceReference camera,
        DeviceReference focuser,
        DeviceReference filterWheel
) {
    public OpticalTrain {
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
