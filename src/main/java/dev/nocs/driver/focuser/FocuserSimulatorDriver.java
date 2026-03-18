package dev.nocs.driver.focuser;

import dev.nocs.domain.Driver;
import dev.nocs.domain.EquipmentType;
import dev.nocs.domain.LogicalDevice;
import dev.nocs.driver.EquipmentDriver;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Focuser simulator driver. Provides a simulated focuser device when loaded.
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
            List.of("0000")
    );

    private static final LogicalDevice SIMULATED_FOCUSER =
            new LogicalDevice("Simulated Focuser", "0000", "0003", EquipmentType.FOCUSER, 0);

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
        return loaded.get() ? List.of(SIMULATED_FOCUSER) : List.of();
    }
}
