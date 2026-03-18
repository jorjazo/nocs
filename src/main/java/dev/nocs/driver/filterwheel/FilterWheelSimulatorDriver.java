package dev.nocs.driver.filterwheel;

import dev.nocs.domain.Driver;
import dev.nocs.domain.LogicalDevice;
import dev.nocs.driver.EquipmentDriver;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * Filter wheel simulator driver. Phase 0: metadata only, no logical devices.
 */
@Component
public class FilterWheelSimulatorDriver implements EquipmentDriver {

    private static final Driver METADATA = new Driver(
            FilterWheelSimulatorDriver.class.getCanonicalName(),
            "Filter Wheel Simulator",
            "In-memory filter wheel simulator for development and testing",
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
