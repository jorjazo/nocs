package dev.nocs.domain.equipment.mount;

/**
 * How the mount driver connects to hardware (host/port for TCP, serial port).
 */
public record MountDriverConfiguration(
        String driverType,
        String host,
        int port,
        String serialPort
) {
    public MountDriverConfiguration {
        if (driverType == null) driverType = "simulator";
        if (host == null) host = "";
        if (port <= 0) port = 4030;
        if (serialPort == null) serialPort = "";
    }
}
