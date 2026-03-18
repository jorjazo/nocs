package dev.nocs.driver.camera;

import dev.nocs.domain.Driver;
import dev.nocs.domain.EquipmentType;
import dev.nocs.domain.LogicalDevice;
import dev.nocs.driver.EquipmentDriver;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Camera simulator driver. Provides a simulated camera device when loaded.
 */
@Component
public class CameraSimulatorDriver implements EquipmentDriver {

    private static final Driver METADATA = new Driver(
            CameraSimulatorDriver.class.getCanonicalName(),
            "Camera Simulator",
            "In-memory camera simulator for development and testing",
            "1.0.0",
            "NOCS",
            "https://github.com/nocs",
            List.of("0000")
    );

    private static final LogicalDevice SIMULATED_CAMERA =
            new LogicalDevice("Simulated Camera", "0000", "0002", EquipmentType.CAMERA, 0);

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
        return loaded.get() ? List.of(SIMULATED_CAMERA) : List.of();
    }
}
