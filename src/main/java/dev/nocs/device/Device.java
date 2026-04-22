package dev.nocs.device;

public interface Device {

    DeviceId id();

    String indiName();

    DeviceKind kind();

    boolean isConnected();

    void connect();

    void disconnect();
}
