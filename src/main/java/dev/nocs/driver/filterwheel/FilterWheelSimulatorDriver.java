package dev.nocs.driver.filterwheel;

import dev.nocs.domain.Driver;
import dev.nocs.domain.EquipmentType;
import dev.nocs.domain.LogicalDevice;
import dev.nocs.driver.EquipmentDriver;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Filter wheel simulator driver. Provides a simulated filter wheel device when loaded.
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
            List.of("0000")
    );

    private static final LogicalDevice SIMULATED_FILTER_WHEEL =
            new LogicalDevice("Simulated Filter Wheel", "0000", "0004", EquipmentType.FILTER_WHEEL, 0);

    private final AtomicBoolean loaded = new AtomicBoolean(false);

    @Override
    public Driver getMetadata() {
        return METADATA;
    }

    @Override
    public void load() {
        loaded.set(true);
    }

    @Override
    public void unload() {
        loaded.set(false);
    }

    @Override
    public boolean isLoaded() {
        return loaded.get();
    }

    @Override
    public List<LogicalDevice> getLogicalDevices() {
        return loaded.get() ? List.of(SIMULATED_FILTER_WHEEL) : List.of();
    }
}
