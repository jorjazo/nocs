package dev.nocs.domain.equipment.filterwheel;

/**
 * How the filter wheel driver connects to hardware (serial port).
 */
public record FilterWheelDriverConfiguration(
        String driverType,
        String serialPort
) {
    public FilterWheelDriverConfiguration {
        if (driverType == null) driverType = "simulator";
        if (serialPort == null) serialPort = "";
    }
}
