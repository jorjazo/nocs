package dev.nocs.device;

public interface Camera extends Device {

    CameraState state();

    void cool(double setpointCelsius);

    /** Starts an exposure (accepted by driver; image arrives asynchronously). */
    void expose(double durationSeconds);

    void abortExposure();

    Double currentTemperatureCelsius();

    @Override
    default DeviceKind kind() {
        return DeviceKind.CAMERA;
    }
}
