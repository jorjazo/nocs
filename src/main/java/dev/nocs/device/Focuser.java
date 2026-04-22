package dev.nocs.device;

public interface Focuser extends Device {

    FocuserState state();

    int currentPosition();

    void moveAbsolute(int position);

    void moveRelative(int delta);

    void abort();

    @Override
    default DeviceKind kind() {
        return DeviceKind.FOCUSER;
    }
}
