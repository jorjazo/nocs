package dev.nocs.driver.eaf;

import dev.nocs.domain.Driver;
import dev.nocs.domain.EquipmentType;
import dev.nocs.domain.LogicalDevice;
import dev.nocs.domain.equipment.DriverStatus;
import dev.nocs.domain.equipment.focuser.FocuserConfiguration;
import dev.nocs.domain.equipment.focuser.FocuserDriverConfiguration;
import dev.nocs.domain.equipment.focuser.FocuserStatus;
import dev.nocs.driver.EquipmentDriver;
import dev.nocs.driver.focuser.FocuserDriver;
import dev.nocs.events.EquipmentEventPublisher;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/**
 * ZWO EAF (Electronic Auto Focuser) driver using the ZWO EAF SDK via JNA.
 * Supports ZWO EAF and EFF (Electronic Filter Focuser) devices (VID 0x03c3).
 * <p>
 * SDK path: NOCS_EAF_SDK_PATH or ../ASI_Camera_SDK/ASI_linux_mac_SDK_V1.41/lib/x64
 * or indi-3rdparty libasi/x64/libEAFFocuser.bin
 */
@Component
public class EafDriver implements EquipmentDriver, FocuserDriver {

    private static final Logger log = LoggerFactory.getLogger(EafDriver.class);

    private static final Driver METADATA = new Driver(
            EafDriver.class.getCanonicalName(),
            "ZWO EAF",
            "ZWO Electronic Auto Focuser (EAF/EFF) via SDK",
            "1.0.0",
            "ZWO",
            "https://www.zwoastro.com",
            List.of("03c3")
    );

    private final EquipmentEventPublisher eventPublisher;
    private final String sdkPath;

    private final AtomicBoolean loaded = new AtomicBoolean(false);
    private final AtomicBoolean connected = new AtomicBoolean(false);
    private final AtomicInteger eafId = new AtomicInteger(-1);
    private final AtomicReference<FocuserConfiguration> configuration = new AtomicReference<>(
            new FocuserConfiguration(50000, 1));
    private final AtomicReference<FocuserDriverConfiguration> driverConfig = new AtomicReference<>(
            new FocuserDriverConfiguration("eaf", "", 0));
    private final AtomicReference<String> lastError = new AtomicReference<>();

    private volatile EafLib lib;
    private final ExecutorService moveCompletionExecutor = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "eaf-move-completion");
        t.setDaemon(true);
        return t;
    });

    public EafDriver(EquipmentEventPublisher eventPublisher,
                     @Value("${nocs.eaf.sdk-path:}") String sdkPath) {
        this.eventPublisher = eventPublisher;
        this.sdkPath = sdkPath != null && !sdkPath.isBlank() ? sdkPath : defaultSdkPath();
    }

    private static String defaultSdkPath() {
        String env = System.getenv("NOCS_EAF_SDK_PATH");
        if (env != null && !env.isBlank()) return env;
        // Shipped libs: native/linux-x64 relative to working dir
        Path shipped = Path.of(System.getProperty("user.dir")).resolve("native/linux-x64");
        if (shipped.resolve("libEAFFocuser.bin").toFile().exists() || shipped.resolve("libEAFFocuser.so").toFile().exists()) {
            return shipped.toString();
        }
        Path asiSdk = Path.of(System.getProperty("user.dir")).getParent()
                .resolve("ASI_Camera_SDK/ASI_linux_mac_SDK_V1.41/lib/x64");
        if (asiSdk.resolve("libEAFFocuser.so").toFile().exists()) {
            return asiSdk.toString();
        }
        Path indi = Path.of(System.getProperty("user.dir")).getParent()
                .resolve("indi-3rdparty/libasi/x64");
        if (indi.resolve("libEAFFocuser.bin").toFile().exists()) {
            return indi.toString();
        }
        Path tmpIndi = Path.of("/tmp/indi-3rdparty/libasi/x64");
        if (tmpIndi.resolve("libEAFFocuser.bin").toFile().exists()) {
            return tmpIndi.toString();
        }
        return "libEAFFocuser";
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
            eventPublisher.publishConnected(EquipmentType.FOCUSER, getDriverStatus());
        } catch (Throwable t) {
            log.error("Failed to load EAF driver", t);
            lastError.set(t.getMessage());
            loaded.set(false);
        }
    }

    private void loadLibrary() {
        if (lib != null) return;
        String libName = "EAFFocuser";
        if (sdkPath != null && !sdkPath.equals("libEAFFocuser")) {
            Path so = Path.of(sdkPath).resolve("libEAFFocuser.so");
            Path bin = Path.of(sdkPath).resolve("libEAFFocuser.bin");
            if (so.toFile().exists()) {
                lib = EafLib.load(so.toAbsolutePath().toString());
            } else if (bin.toFile().exists()) {
                lib = EafLib.load(bin.toAbsolutePath().toString());
            } else {
                throw new IllegalStateException("EAF SDK not found at " + sdkPath);
            }
        } else {
            lib = EafLib.load(libName);
        }
    }

    @Override
    public void unload() {
        if (!loaded.getAndSet(false)) return;
        disconnect();
        lib = null;
        eventPublisher.publishDisconnected(EquipmentType.FOCUSER, "Profile unloaded");
    }

    @Override
    public boolean isLoaded() {
        return loaded.get();
    }

    @Override
    public List<LogicalDevice> getLogicalDevices() {
        if (!loaded.get() || lib == null) return List.of();
        int n = lib.EAFGetNum();
        if (n <= 0) return List.of();
        int connectedId = eafId.get();
        var devices = new java.util.ArrayList<LogicalDevice>();
        for (int i = 0; i < n; i++) {
            var idRef = new com.sun.jna.ptr.IntByReference();
            if (lib.EAFGetID(i, idRef) == EafLib.EAF_SUCCESS) {
                int id = idRef.getValue();
                var info = new EafInfo.ByReference();
                if (lib.EAFOpen(id) == EafLib.EAF_SUCCESS) {
                    if (lib.EAFGetProperty(id, info) == EafLib.EAF_SUCCESS) {
                        devices.add(new LogicalDevice(
                                info.getName(),
                                "03c3",
                                "1f10",
                                EquipmentType.FOCUSER,
                                i));
                    }
                    if (id != connectedId) {
                        lib.EAFClose(id);
                    }
                }
            }
        }
        return devices;
    }

    @Override
    public FocuserStatus getStatus() {
        if (lib == null || !connected.get()) {
            return new FocuserStatus(0, false, 20.0);
        }
        int id = eafId.get();
        if (id < 0) return new FocuserStatus(0, false, 20.0);
        var posRef = new com.sun.jna.ptr.IntByReference();
        var movingRef = new com.sun.jna.ptr.IntByReference();
        var handRef = new com.sun.jna.ptr.IntByReference();
        int pos = 0;
        boolean moving = false;
        double temp = 20.0;
        if (lib.EAFGetPosition(id, posRef) == EafLib.EAF_SUCCESS) {
            pos = posRef.getValue();
        }
        if (lib.EAFIsMoving(id, movingRef, handRef) == EafLib.EAF_SUCCESS) {
            moving = movingRef.getValue() != 0;
        }
        float[] tempArr = new float[1];
        if (lib.EAFGetTemp(id, tempArr) == EafLib.EAF_SUCCESS && tempArr[0] > -200) {
            temp = tempArr[0];
        }
        return new FocuserStatus(pos, moving, temp);
    }

    @Override
    public FocuserConfiguration getConfiguration() {
        if (lib != null && connected.get()) {
            int id = eafId.get();
            if (id >= 0) {
                var maxRef = new com.sun.jna.ptr.IntByReference();
                if (lib.EAFGetMaxStep(id, maxRef) == EafLib.EAF_SUCCESS) {
                    configuration.set(new FocuserConfiguration(maxRef.getValue(), 1));
                }
            }
        }
        return configuration.get();
    }

    @Override
    public void setConfiguration(FocuserConfiguration config) {
        configuration.set(config);
        if (lib != null && connected.get()) {
            int id = eafId.get();
            if (id >= 0 && lib.EAFSetMaxStep(id, config.maxPosition()) != EafLib.EAF_SUCCESS) {
                log.warn("Failed to set EAF max step");
            }
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
    public FocuserDriverConfiguration getDriverConfiguration() {
        return driverConfig.get();
    }

    @Override
    public void setDriverConfiguration(FocuserDriverConfiguration config) {
        driverConfig.set(config);
    }

    @Override
    public void connect() {
        if (lib == null || !loaded.get()) return;
        if (connected.get()) return;
        lastError.set(null);
        int index = driverConfig.get().deviceIndex();
        int n = lib.EAFGetNum();
        if (n <= 0 || index >= n) {
            lastError.set("No EAF at index " + index);
            return;
        }
        var idRef = new com.sun.jna.ptr.IntByReference();
        if (lib.EAFGetID(index, idRef) != EafLib.EAF_SUCCESS) {
            lastError.set("EAFGetID failed");
            return;
        }
        int id = idRef.getValue();
        if (lib.EAFOpen(id) != EafLib.EAF_SUCCESS) {
            lastError.set("EAFOpen failed");
            return;
        }
        var info = new EafInfo.ByReference();
        if (lib.EAFGetProperty(id, info) == EafLib.EAF_SUCCESS) {
            configuration.set(new FocuserConfiguration(info.MaxStep, 1));
        }
        eafId.set(id);
        connected.set(true);
        eventPublisher.publishConnected(EquipmentType.FOCUSER, getDriverStatus());
        eventPublisher.publishStatusChanged(EquipmentType.FOCUSER, getStatus(), getDriverStatus());
    }

    @Override
    public void disconnect() {
        if (!connected.getAndSet(false)) return;
        int id = eafId.getAndSet(-1);
        if (lib != null && id >= 0) {
            lib.EAFClose(id);
        }
        eventPublisher.publishDisconnected(EquipmentType.FOCUSER, "Disconnected");
    }

    @Override
    public void moveRelative(int steps) {
        if (lib == null || !connected.get()) return;
        int id = eafId.get();
        if (id < 0) return;
        int pos = 0;
        var posRef = new com.sun.jna.ptr.IntByReference();
        if (lib.EAFGetPosition(id, posRef) == EafLib.EAF_SUCCESS) {
            pos = posRef.getValue();
        }
        int target = Math.max(0, Math.min(pos + steps, configuration.get().maxPosition()));
        moveAbsolute(target);
    }

    @Override
    public void moveAbsolute(int position) {
        if (lib == null || !connected.get()) return;
        int id = eafId.get();
        if (id < 0) return;
        int clamped = Math.max(0, Math.min(position, configuration.get().maxPosition()));
        int r = lib.EAFMove(id, clamped);
        if (r != EafLib.EAF_SUCCESS && r != EafLib.EAF_ERROR_MOVING) {
            String err = switch (r) {
                case EafLib.EAF_ERROR_CLOSED -> "EAF closed (device may have been closed by another call)";
                case EafLib.EAF_ERROR_MOVING -> "EAF busy moving";
                default -> "EAF error " + r;
            };
            log.warn("EAFMove failed: {}", err);
        }
        eventPublisher.publishStatusChanged(EquipmentType.FOCUSER, getStatus(), getDriverStatus());
        moveCompletionExecutor.submit(this::pollUntilMoveComplete);
    }

    private void pollUntilMoveComplete() {
        int id = eafId.get();
        if (id < 0 || lib == null || !connected.get()) return;
        var movingRef = new com.sun.jna.ptr.IntByReference();
        var handRef = new com.sun.jna.ptr.IntByReference();
        try {
            while (connected.get() && lib != null) {
                if (lib.EAFIsMoving(id, movingRef, handRef) != EafLib.EAF_SUCCESS) break;
                eventPublisher.publishStatusChanged(EquipmentType.FOCUSER, getStatus(), getDriverStatus());
                if (movingRef.getValue() == 0) return;
                Thread.sleep(500);
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
