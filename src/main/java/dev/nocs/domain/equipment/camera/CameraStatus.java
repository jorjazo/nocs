package dev.nocs.domain.equipment.camera;

/**
 * Current live state of the camera.
 */
public record CameraStatus(
        boolean exposing,
        double temperatureCelsius,
        String currentFrameId
) {
    public CameraStatus {
        if (currentFrameId == null) currentFrameId = "";
    }
}
