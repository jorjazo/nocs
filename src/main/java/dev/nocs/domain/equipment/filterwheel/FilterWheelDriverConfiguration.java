package dev.nocs.domain.equipment.filterwheel;

/**
 * How the filter wheel driver connects to hardware.
 * - simulator: no hardware, serialPort/deviceIndex ignored
 * - efw: ZWO EFW via SDK, deviceIndex selects which EFW (0-based), serialPort ignored
 */
public record FilterWheelDriverConfiguration(
        String driverType,
        String serialPort,
        Integer deviceIndex
) {
    public FilterWheelDriverConfiguration {
        if (driverType == null) driverType = "simulator";
        if (serialPort == null) serialPort = "";
        if (deviceIndex == null) deviceIndex = 0;
    }

    public FilterWheelDriverConfiguration(String driverType, String serialPort) {
        this(driverType, serialPort, 0);
    }
}
