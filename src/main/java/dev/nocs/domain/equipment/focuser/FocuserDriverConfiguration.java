package dev.nocs.domain.equipment.focuser;

/**
 * How the focuser driver connects to hardware.
 * - simulator: no hardware, serialPort ignored
 * - eaf: ZWO EAF via SDK, deviceIndex selects which EAF (0-based), serialPort ignored
 */
public record FocuserDriverConfiguration(
        String driverType,
        String serialPort,
        Integer deviceIndex
) {
    public FocuserDriverConfiguration {
        if (driverType == null) driverType = "simulator";
        if (serialPort == null) serialPort = "";
        if (deviceIndex == null) deviceIndex = 0;
    }

    public FocuserDriverConfiguration(String driverType, String serialPort) {
        this(driverType, serialPort, 0);
    }
}
