package dev.nocs.driver.focuser;

import dev.nocs.domain.Driver;
import dev.nocs.domain.LogicalDevice;
import dev.nocs.driver.EquipmentDriver;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * Focuser simulator driver. Phase 0: metadata only, no logical devices.
 */
@Component
public class FocuserSimulatorDriver implements EquipmentDriver {

    private static final Driver METADATA = new Driver(
            FocuserSimulatorDriver.class.getCanonicalName(),
            "Focuser Simulator",
            "In-memory focuser simulator for development and testing",
            "1.0.0",
            "NOCS",
            "https://github.com/nocs",
            List.of()
    );

    @Override
    public Driver getMetadata() {
        return METADATA;
    }

    @Override
    public List<LogicalDevice> getLogicalDevices() {
        return List.of();
    }
}
