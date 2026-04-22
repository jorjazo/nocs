package dev.nocs.device;

public interface Mount extends Device {

    MountState state();

    void slew(double raHours, double decDegrees);

    void syncTo(double raHours, double decDegrees);

    void park();

    void unpark();

    void abort();

    @Override
    default DeviceKind kind() {
        return DeviceKind.MOUNT;
    }
}
