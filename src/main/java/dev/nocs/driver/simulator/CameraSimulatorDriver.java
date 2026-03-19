package dev.nocs.driver.simulator;

import dev.nocs.domain.Driver;
import dev.nocs.domain.EquipmentType;
import dev.nocs.domain.LogicalDevice;
import dev.nocs.domain.equipment.DriverStatus;
import dev.nocs.domain.equipment.camera.CameraConfiguration;
import dev.nocs.domain.equipment.camera.CameraDriverConfiguration;
import dev.nocs.domain.equipment.camera.CameraStatus;
import dev.nocs.driver.EquipmentDriver;
import dev.nocs.driver.camera.CameraDriver;
import dev.nocs.events.EquipmentEventPublisher;
import dev.nocs.service.ImageMetadata;
import dev.nocs.service.ImageStorageService;
import org.springframework.stereotype.Component;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Random;
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
    private static final int SIM_WIDTH = 640;
    private static final int SIM_HEIGHT = 480;

    private final EquipmentEventPublisher eventPublisher;
    private final ImageStorageService imageStorage;

    public CameraSimulatorDriver(EquipmentEventPublisher eventPublisher, ImageStorageService imageStorage) {
        this.eventPublisher = eventPublisher;
        this.imageStorage = imageStorage;
    }

    @Override
    public Driver getMetadata() {
        return METADATA;
    }

    @Override
    public void load() {
        loaded.set(true);
        eventPublisher.publishConnected(EquipmentType.CAMERA, getDriverStatus());
        eventPublisher.publishStatusChanged(EquipmentType.CAMERA, status.get());
    }

    @Override
    public void unload() {
        loaded.set(false);
        eventPublisher.publishDisconnected(EquipmentType.CAMERA, "Profile unloaded");
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
        eventPublisher.publishStatusChanged(EquipmentType.CAMERA, status.get());
        long durationMs = (long) (durationSeconds * 1000);
        CameraConfiguration cfg = configuration.get();
        Instant dateObs = Instant.now();
        new Thread(() -> {
            try {
                Thread.sleep(Math.min(durationMs, 3000));
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
            byte[] rawData = generateSyntheticImage(SIM_WIDTH, SIM_HEIGHT);
            completedFrames.put(frameId, rawData);
            var meta = new ImageMetadata("Simulated Camera", cfg.gain(), cfg.offset(),
                    durationSeconds, status.get().temperatureCelsius(), cfg.binning(),
                    SIM_WIDTH, SIM_HEIGHT, 16, 3.8, dateObs);
            imageStorage.saveExposure(frameId, rawData, meta);
            status.set(new CameraStatus(false, status.get().temperatureCelsius(), frameId));
            eventPublisher.publishStatusChanged(EquipmentType.CAMERA, status.get());
        }).start();
        return frameId;
    }

    private static byte[] generateSyntheticImage(int width, int height) {
        var rng = new Random();
        ByteBuffer buf = ByteBuffer.allocate(width * height * 2).order(ByteOrder.LITTLE_ENDIAN);
        for (int y = 0; y < height; y++) {
            for (int x = 0; x < width; x++) {
                int gradient = (int) ((double) (x + y) / (width + height) * 8000) + 800;
                int noise = rng.nextInt(400) - 200;
                buf.putShort((short) Math.min(65535, Math.max(0, gradient + noise)));
            }
        }
        // sprinkle a few synthetic "stars"
        for (int s = 0; s < 30; s++) {
            int cx = rng.nextInt(width - 10) + 5;
            int cy = rng.nextInt(height - 10) + 5;
            int brightness = 20000 + rng.nextInt(40000);
            for (int dy = -3; dy <= 3; dy++) {
                for (int dx = -3; dx <= 3; dx++) {
                    double dist = Math.sqrt(dx * dx + dy * dy);
                    if (dist > 3.5) continue;
                    int val = (int) (brightness * Math.exp(-dist * dist / 2.0));
                    int idx = ((cy + dy) * width + (cx + dx)) * 2;
                    if (idx >= 0 && idx + 1 < buf.capacity()) {
                        int existing = buf.getShort(idx) & 0xFFFF;
                        buf.putShort(idx, (short) Math.min(65535, existing + val));
                    }
                }
            }
        }
        return buf.array();
    }

    @Override
    public byte[] getImage(String frameId) {
        return Optional.ofNullable(completedFrames.get(frameId)).orElse(new byte[0]);
    }
}
