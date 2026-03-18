package dev.nocs.driver.mount;

import dev.nocs.domain.Driver;
import dev.nocs.domain.EquipmentType;
import dev.nocs.domain.LogicalDevice;
import dev.nocs.driver.EquipmentDriver;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Mount simulator driver. Provides a simulated mount device when loaded.
 */
@Component
public class MountSimulatorDriver implements EquipmentDriver {

    private static final Driver METADATA = new Driver(
            MountSimulatorDriver.class.getCanonicalName(),
            "Mount Simulator",
            "In-memory mount simulator for development and testing",
            "1.0.0",
            "NOCS",
            "https://github.com/nocs",
            List.of("0000")
    );

    private static final LogicalDevice SIMULATED_MOUNT =
            new LogicalDevice("Simulated Mount", "0000", "0001", EquipmentType.MOUNT, 0);

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
        return loaded.get() ? List.of(SIMULATED_MOUNT) : List.of();
    }
}
