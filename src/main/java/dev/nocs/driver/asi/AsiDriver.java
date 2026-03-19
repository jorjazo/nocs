package dev.nocs.driver.asi;

import com.sun.jna.Memory;
import com.sun.jna.NativeLong;
import com.sun.jna.ptr.IntByReference;
import com.sun.jna.ptr.NativeLongByReference;
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
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/**
 * ZWO ASI Camera driver using the ZWO ASI Camera SDK via JNA.
 * Supports all ZWO ASI cameras (VID 0x03c3). Uses the snap/long-exposure API
 * (ASIStartExposure → ASIGetExpStatus → ASIGetDataAfterExp) for image capture.
 * Images are captured as RAW16 (16-bit mono).
 */
@Component
public class AsiDriver implements EquipmentDriver, CameraDriver {

    private static final Logger log = LoggerFactory.getLogger(AsiDriver.class);

    static final Driver METADATA = new Driver(
            AsiDriver.class.getCanonicalName(),
            "ZWO ASI Camera",
            "ZWO ASI Camera via SDK (ASI1600, ASI294, ASI533, etc.)",
            "1.0.0",
            "ZWO",
            "https://www.zwoastro.com",
            List.of("03c3")
    );

    private static final int IMAGE_TYPE = AsiLib.ASI_IMG_RAW16;
    private static final int BYTES_PER_PIXEL_RAW16 = 2;

    private final EquipmentEventPublisher eventPublisher;
    private final ImageStorageService imageStorage;
    private final String sdkPath;

    private final AtomicBoolean loaded = new AtomicBoolean(false);
    private final AtomicBoolean connected = new AtomicBoolean(false);
    private final AtomicBoolean exposing = new AtomicBoolean(false);
    private final AtomicInteger cameraId = new AtomicInteger(-1);
    private final AtomicReference<CameraConfiguration> configuration = new AtomicReference<>(
            new CameraConfiguration(0, 10, 1, 0, 0, 4656, 3520));
    private final AtomicReference<CameraDriverConfiguration> driverConfig = new AtomicReference<>(
            new CameraDriverConfiguration("asi", 0));
    private final AtomicReference<String> lastError = new AtomicReference<>();
    private final AtomicReference<String> currentFrameId = new AtomicReference<>("");
    private final AtomicInteger frameIdCounter = new AtomicInteger(0);
    private final Map<String, byte[]> completedFrames = new ConcurrentHashMap<>();

    private volatile AsiLib lib;
    private volatile int maxWidth;
    private volatile int maxHeight;
    private volatile String cameraName = "";
    private volatile double pixelSizeMicrons;
    private volatile int bitDepth = 16;

    private final ExecutorService exposureExecutor = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "asi-exposure");
        t.setDaemon(true);
        return t;
    });

    public AsiDriver(EquipmentEventPublisher eventPublisher,
                     ImageStorageService imageStorage,
                     @Value("${nocs.asi.sdk-path:}") String sdkPath) {
        this.eventPublisher = eventPublisher;
        this.imageStorage = imageStorage;
        this.sdkPath = sdkPath != null && !sdkPath.isBlank() ? sdkPath : defaultSdkPath();
    }

    private static String defaultSdkPath() {
        String env = System.getenv("NOCS_ASI_SDK_PATH");
        if (env != null && !env.isBlank()) return env;
        Path shipped = Path.of(System.getProperty("user.dir")).resolve("native/linux-x64");
        if (shipped.resolve("libASICamera2.so").toFile().exists()) {
            return shipped.toString();
        }
        Path asiSdk = Path.of(System.getProperty("user.dir")).getParent()
                .resolve("ASI_Camera_SDK/ASI_linux_mac_SDK_V1.41/lib/x64");
        if (asiSdk.resolve("libASICamera2.so").toFile().exists()) {
            return asiSdk.toString();
        }
        return "libASICamera2";
    }

    @Override
    public Driver getMetadata() {
        return METADATA;
    }

    @Override
    public void load() {
        if (loaded.getAndSet(true)) return;
        try {
            loadLibrary();
            log.info("ASI Camera SDK loaded (version: {})", lib.ASIGetSDKVersion());
            eventPublisher.publishConnected(EquipmentType.CAMERA, getDriverStatus());
        } catch (Throwable t) {
            log.error("Failed to load ASI Camera driver", t);
            lastError.set(t.getMessage());
            loaded.set(false);
        }
    }

    private void loadLibrary() {
        if (lib != null) return;
        if (sdkPath != null && !sdkPath.equals("libASICamera2")) {
            Path so = Path.of(sdkPath).resolve("libASICamera2.so");
            if (so.toFile().exists()) {
                lib = AsiLib.load(so.toAbsolutePath().toString());
            } else {
                throw new IllegalStateException("ASI Camera SDK not found at " + sdkPath);
            }
        } else {
            lib = AsiLib.load("ASICamera2");
        }
    }

    @Override
    public void unload() {
        if (!loaded.getAndSet(false)) return;
        disconnect();
        lib = null;
        completedFrames.clear();
        eventPublisher.publishDisconnected(EquipmentType.CAMERA, "Profile unloaded");
    }

    @Override
    public boolean isLoaded() {
        return loaded.get();
    }

    @Override
    public List<LogicalDevice> getLogicalDevices() {
        if (!loaded.get() || lib == null) return List.of();
        int n = lib.ASIGetNumOfConnectedCameras();
        if (n <= 0) return List.of();
        var devices = new ArrayList<LogicalDevice>();
        for (int i = 0; i < n; i++) {
            var info = new AsiCameraInfo.ByReference();
            if (lib.ASIGetCameraProperty(info, i) == AsiLib.ASI_SUCCESS) {
                devices.add(new LogicalDevice(
                        info.getName(),
                        "03c3",
                        "1604",
                        EquipmentType.CAMERA,
                        i));
            }
        }
        return devices;
    }

    @Override
    public CameraStatus getStatus() {
        double temp = readTemperature();
        return new CameraStatus(exposing.get(), temp, currentFrameId.get());
    }

    @Override
    public CameraConfiguration getConfiguration() {
        return configuration.get();
    }

    @Override
    public void setConfiguration(CameraConfiguration config) {
        configuration.set(config);
        if (lib != null && connected.get() && !exposing.get()) {
            applyConfiguration(config);
        }
    }

    @Override
    public DriverStatus getDriverStatus() {
        if (!loaded.get()) {
            return new DriverStatus(DriverStatus.ConnectionState.DISCONNECTED, lastError.get());
        }
        if (connected.get()) {
            return new DriverStatus(DriverStatus.ConnectionState.CONNECTED, null);
        }
        return new DriverStatus(DriverStatus.ConnectionState.DISCONNECTED, lastError.get());
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
        if (lib == null || !loaded.get()) return;
        if (connected.get()) return;
        lastError.set(null);

        int index = driverConfig.get().cameraIndex();
        int n = lib.ASIGetNumOfConnectedCameras();
        if (n <= 0 || index >= n) {
            lastError.set("No ASI camera at index " + index);
            return;
        }

        var info = new AsiCameraInfo.ByReference();
        if (lib.ASIGetCameraProperty(info, index) != AsiLib.ASI_SUCCESS) {
            lastError.set("ASIGetCameraProperty failed for index " + index);
            return;
        }

        int id = info.CameraID;
        int r = lib.ASIOpenCamera(id);
        if (r != AsiLib.ASI_SUCCESS) {
            lastError.set("ASIOpenCamera failed: error " + r);
            return;
        }

        r = lib.ASIInitCamera(id);
        if (r != AsiLib.ASI_SUCCESS) {
            lib.ASICloseCamera(id);
            lastError.set("ASIInitCamera failed: error " + r);
            return;
        }

        maxWidth = info.getMaxWidth();
        maxHeight = info.getMaxHeight();
        cameraName = info.getName();
        pixelSizeMicrons = info.PixelSize;
        bitDepth = info.BitDepth;
        cameraId.set(id);
        connected.set(true);

        CameraConfiguration cfg = configuration.get();
        int roiW = cfg.roiWidth() > 0 ? cfg.roiWidth() : maxWidth;
        int roiH = cfg.roiHeight() > 0 ? cfg.roiHeight() : maxHeight;
        configuration.set(new CameraConfiguration(cfg.gain(), cfg.offset(), cfg.binning(),
                cfg.roiX(), cfg.roiY(), roiW, roiH));

        applyConfiguration(configuration.get());

        log.info("Connected to ASI camera: {} (ID={}, {}x{}, cooler={})",
                info.getName(), id, maxWidth, maxHeight, info.isCoolerCam());

        eventPublisher.publishConnected(EquipmentType.CAMERA, getDriverStatus());
        eventPublisher.publishStatusChanged(EquipmentType.CAMERA, getStatus(), getDriverStatus());
    }

    @Override
    public void disconnect() {
        if (!connected.getAndSet(false)) return;
        if (exposing.get()) {
            int id = cameraId.get();
            if (lib != null && id >= 0) {
                lib.ASIStopExposure(id);
            }
            exposing.set(false);
        }
        int id = cameraId.getAndSet(-1);
        if (lib != null && id >= 0) {
            lib.ASICloseCamera(id);
        }
        eventPublisher.publishDisconnected(EquipmentType.CAMERA, "Disconnected");
    }

    @Override
    public String startExposure(double durationSeconds) {
        if (lib == null || !connected.get()) {
            throw new IllegalStateException("Camera not connected");
        }
        if (exposing.get()) {
            throw new IllegalStateException("Exposure already in progress");
        }

        int id = cameraId.get();
        if (id < 0) throw new IllegalStateException("Invalid camera ID");

        long exposureUs = (long) (durationSeconds * 1_000_000);
        setControlValue(id, AsiLib.ASI_EXPOSURE, exposureUs);

        CameraConfiguration cfg = configuration.get();
        setControlValue(id, AsiLib.ASI_GAIN, cfg.gain());
        setControlValue(id, AsiLib.ASI_OFFSET, cfg.offset());

        String frameId = "frame-" + frameIdCounter.incrementAndGet();
        currentFrameId.set(frameId);
        exposing.set(true);
        Instant dateObs = Instant.now();

        int r = lib.ASIStartExposure(id, AsiLib.ASI_FALSE);
        if (r != AsiLib.ASI_SUCCESS) {
            exposing.set(false);
            String err = "ASIStartExposure failed: error " + r;
            log.error(err);
            throw new IllegalStateException(err);
        }

        eventPublisher.publishStatusChanged(EquipmentType.CAMERA, getStatus(), getDriverStatus());

        int captureWidth = cfg.roiWidth() / cfg.binning();
        int captureHeight = cfg.roiHeight() / cfg.binning();
        exposureExecutor.submit(() -> pollExposureCompletion(
                id, frameId, captureWidth, captureHeight, durationSeconds, cfg, dateObs));

        return frameId;
    }

    @Override
    public byte[] getImage(String frameId) {
        byte[] data = completedFrames.get(frameId);
        return data != null ? data : new byte[0];
    }

    private void pollExposureCompletion(int id, String frameId, int width, int height,
                                        double durationSeconds, CameraConfiguration cfg, Instant dateObs) {
        var statusRef = new IntByReference();
        try {
            while (connected.get() && exposing.get() && lib != null) {
                int r = lib.ASIGetExpStatus(id, statusRef);
                if (r != AsiLib.ASI_SUCCESS) {
                    log.error("ASIGetExpStatus failed: error {}", r);
                    break;
                }

                int expStatus = statusRef.getValue();
                if (expStatus == AsiLib.ASI_EXP_SUCCESS) {
                    long bufferSize = (long) width * height * BYTES_PER_PIXEL_RAW16;
                    Memory buffer = new Memory(bufferSize);
                    r = lib.ASIGetDataAfterExp(id, buffer, new NativeLong(bufferSize));
                    if (r == AsiLib.ASI_SUCCESS) {
                        byte[] imageData = buffer.getByteArray(0, (int) bufferSize);
                        completedFrames.put(frameId, imageData);
                        log.info("Exposure complete: {} ({}x{}, {} bytes)", frameId, width, height, imageData.length);

                        var meta = new ImageMetadata(
                                cameraName, cfg.gain(), cfg.offset(), durationSeconds,
                                readTemperature(), cfg.binning(), width, height,
                                bitDepth, pixelSizeMicrons, dateObs);
                        imageStorage.saveExposure(frameId, imageData, meta);
                    } else {
                        log.error("ASIGetDataAfterExp failed: error {}", r);
                    }
                    exposing.set(false);
                    eventPublisher.publishStatusChanged(EquipmentType.CAMERA, getStatus(), getDriverStatus());
                    return;
                }

                if (expStatus == AsiLib.ASI_EXP_FAILED) {
                    log.error("Exposure failed for frame {}", frameId);
                    exposing.set(false);
                    eventPublisher.publishStatusChanged(EquipmentType.CAMERA, getStatus(), getDriverStatus());
                    return;
                }

                Thread.sleep(200);
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } finally {
            exposing.set(false);
        }
    }

    private void applyConfiguration(CameraConfiguration cfg) {
        int id = cameraId.get();
        if (id < 0 || lib == null) return;

        int width = alignDown(cfg.roiWidth() / cfg.binning(), 8);
        int height = alignDown(cfg.roiHeight() / cfg.binning(), 2);
        if (width <= 0) width = alignDown(maxWidth / cfg.binning(), 8);
        if (height <= 0) height = alignDown(maxHeight / cfg.binning(), 2);

        int r = lib.ASISetROIFormat(id, width, height, cfg.binning(), IMAGE_TYPE);
        if (r != AsiLib.ASI_SUCCESS) {
            log.warn("ASISetROIFormat({}, {}, bin{}) failed: error {}", width, height, cfg.binning(), r);
        }

        if (cfg.roiX() > 0 || cfg.roiY() > 0) {
            r = lib.ASISetStartPos(id, cfg.roiX(), cfg.roiY());
            if (r != AsiLib.ASI_SUCCESS) {
                log.warn("ASISetStartPos({}, {}) failed: error {}", cfg.roiX(), cfg.roiY(), r);
            }
        }

        setControlValue(id, AsiLib.ASI_GAIN, cfg.gain());
        setControlValue(id, AsiLib.ASI_OFFSET, cfg.offset());
    }

    private void setControlValue(int id, int controlType, long value) {
        if (lib == null) return;
        int r = lib.ASISetControlValue(id, controlType, new NativeLong(value), AsiLib.ASI_FALSE);
        if (r != AsiLib.ASI_SUCCESS) {
            log.warn("ASISetControlValue(type={}, value={}) failed: error {}", controlType, value, r);
        }
    }

    private double readTemperature() {
        if (lib == null || !connected.get()) return 20.0;
        int id = cameraId.get();
        if (id < 0) return 20.0;
        var valueRef = new NativeLongByReference();
        var autoRef = new IntByReference();
        if (lib.ASIGetControlValue(id, AsiLib.ASI_TEMPERATURE, valueRef, autoRef) == AsiLib.ASI_SUCCESS) {
            return valueRef.getValue().longValue() / 10.0;
        }
        return 20.0;
    }

    private static int alignDown(int value, int alignment) {
        return (value / alignment) * alignment;
    }
}
