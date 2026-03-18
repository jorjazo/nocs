package dev.nocs.driver.camera;

import dev.nocs.domain.Driver;
import dev.nocs.domain.EquipmentType;
import dev.nocs.domain.LogicalDevice;
import dev.nocs.domain.equipment.DriverStatus;
import dev.nocs.domain.equipment.camera.CameraConfiguration;
import dev.nocs.domain.equipment.camera.CameraDriverConfiguration;
import dev.nocs.domain.equipment.camera.CameraStatus;
import dev.nocs.driver.EquipmentDriver;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Camera simulator driver. Provides a simulated camera device when loaded.
 */
@Component
public class CameraSimulatorDriver implements EquipmentDriver, CameraDriver {

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
    private final AtomicReference<CameraStatus> status = new AtomicReference<>(
            new CameraStatus(false, -10.0, ""));
    private final AtomicReference<CameraConfiguration> configuration = new AtomicReference<>(
            new CameraConfiguration(100, 50, 1, 0, 0, 4656, 3520));
    private final AtomicReference<CameraDriverConfiguration> driverConfig = new AtomicReference<>(
            new CameraDriverConfiguration("simulator", 0));
    private final AtomicInteger frameIdCounter = new AtomicInteger(0);
    private final Map<String, byte[]> completedFrames = new ConcurrentHashMap<>();

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

    @Override
    public CameraStatus getStatus() {
        return status.get();
    }

    @Override
    public CameraConfiguration getConfiguration() {
        return configuration.get();
    }

    @Override
    public void setConfiguration(CameraConfiguration config) {
        configuration.set(config);
    }

    @Override
    public DriverStatus getDriverStatus() {
        return loaded.get()
                ? new DriverStatus(DriverStatus.ConnectionState.CONNECTED, null)
                : new DriverStatus(DriverStatus.ConnectionState.DISCONNECTED, null);
    }

    @Override
    public CameraDriverConfiguration getDriverConfiguration() {
        return driverConfig.get();
    }

    @Override
    public void setDriverConfiguration(CameraDriverConfiguration config) {
        driverConfig.set(config);
    }

    @Override
    public void connect() {
        // Simulator: no-op when loaded
    }

    @Override
    public void disconnect() {
        // Simulator: no-op
    }

    @Override
    public String startExposure(double durationSeconds) {
        String frameId = "frame-" + frameIdCounter.incrementAndGet();
        status.set(new CameraStatus(true, status.get().temperatureCelsius(), frameId));
        long durationMs = (long) (durationSeconds * 1000);
        new Thread(() -> {
            try {
                Thread.sleep(Math.min(durationMs, 3000));
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
            completedFrames.put(frameId, new byte[0]);
            status.set(new CameraStatus(false, status.get().temperatureCelsius(), frameId));
        }).start();
        return frameId;
    }

    @Override
    public byte[] getImage(String frameId) {
        return Optional.ofNullable(completedFrames.get(frameId)).orElse(new byte[0]);
    }
}
