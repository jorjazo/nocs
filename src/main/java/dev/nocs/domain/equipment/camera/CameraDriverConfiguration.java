package dev.nocs.domain.equipment.camera;

/**
 * How the camera driver connects to hardware (camera index, USB).
 */
public record CameraDriverConfiguration(
        String driverType,
        int cameraIndex
) {
    public CameraDriverConfiguration {
        if (driverType == null) driverType = "simulator";
        if (cameraIndex < 0) cameraIndex = 0;
    }
}
