package dev.nocs.device;

public interface CameraImageSink {

    /** Must not block the INDI reader thread for long. */
    void accept(DeviceId camera, byte[] bytes, String extension);
}
