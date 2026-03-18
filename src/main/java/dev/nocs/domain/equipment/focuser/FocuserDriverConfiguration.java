package dev.nocs.domain.equipment.focuser;

/**
 * How the focuser driver connects to hardware (serial port).
 */
public record FocuserDriverConfiguration(
        String driverType,
        String serialPort
) {
    public FocuserDriverConfiguration {
        if (driverType == null) driverType = "simulator";
        if (serialPort == null) serialPort = "";
    }
}
