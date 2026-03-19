package dev.nocs.driver.efw;

import dev.nocs.domain.Driver;
import dev.nocs.domain.EquipmentType;
import dev.nocs.domain.LogicalDevice;
import dev.nocs.domain.equipment.DriverStatus;
import dev.nocs.domain.equipment.filterwheel.FilterWheelConfiguration;
import dev.nocs.domain.equipment.filterwheel.FilterWheelDriverConfiguration;
import dev.nocs.domain.equipment.filterwheel.FilterWheelStatus;
import dev.nocs.driver.EquipmentDriver;
import dev.nocs.driver.filterwheel.FilterWheelDriver;
import dev.nocs.events.EquipmentEventPublisher;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.stream.IntStream;

/**
 * ZWO EFW (Electronic Filter Wheel) driver using the ZWO EFW SDK via JNA.
 * Supports ZWO EFW devices (VID 0x03c3).
 * <p>
 * SDK path: NOCS_EFW_SDK_PATH env var, nocs.efw.sdk-path property,
 * or native/linux-x64/libEFWFilter.bin shipped with the project.
 */
@Component
public class EfwDriver implements EquipmentDriver, FilterWheelDriver {

    private static final Logger log = LoggerFactory.getLogger(EfwDriver.class);

    private static final Driver METADATA = new Driver(
            EfwDriver.class.getCanonicalName(),
            "ZWO EFW",
            "ZWO Electronic Filter Wheel (EFW) via SDK",
            "1.0.0",
            "ZWO",
            "https://www.zwoastro.com",
            List.of("03c3")
    );

    private static final List<String> DEFAULT_FILTERS = List.of("L", "R", "G", "B", "Ha", "SII", "OIII");

    private final EquipmentEventPublisher eventPublisher;
    private final String sdkPath;

    private final AtomicBoolean loaded = new AtomicBoolean(false);
    private final AtomicBoolean connected = new AtomicBoolean(false);
    private final AtomicInteger efwId = new AtomicInteger(-1);
    private final AtomicInteger slotCount = new AtomicInteger(7);
    private final AtomicReference<FilterWheelConfiguration> configuration = new AtomicReference<>(
            new FilterWheelConfiguration(DEFAULT_FILTERS));
    private final AtomicReference<FilterWheelDriverConfiguration> driverConfig = new AtomicReference<>(
            new FilterWheelDriverConfiguration("efw", "", 0));
    private final AtomicReference<String> lastError = new AtomicReference<>();

    private volatile EfwLib lib;
    private final ExecutorService moveCompletionExecutor = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "efw-move-completion");
        t.setDaemon(true);
        return t;
    });

    public EfwDriver(EquipmentEventPublisher eventPublisher,
                     @Value("${nocs.efw.sdk-path:}") String sdkPath) {
        this.eventPublisher = eventPublisher;
        this.sdkPath = sdkPath != null && !sdkPath.isBlank() ? sdkPath : defaultSdkPath();
    }

    private static String defaultSdkPath() {
        String env = System.getenv("NOCS_EFW_SDK_PATH");
        if (env != null && !env.isBlank()) return env;
        Path shipped = Path.of(System.getProperty("user.dir")).resolve("native/linux-x64");
        if (shipped.resolve("libEFWFilter.bin").toFile().exists() || shipped.resolve("libEFWFilter.so").toFile().exists()) {
            return shipped.toString();
        }
        Path indi = Path.of(System.getProperty("user.dir")).getParent()
                .resolve("indi-3rdparty/libasi/x64");
        if (indi.resolve("libEFWFilter.bin").toFile().exists()) {
            return indi.toString();
        }
        Path tmpIndi = Path.of("/tmp/indi-3rdparty/libasi/x64");
        if (tmpIndi.resolve("libEFWFilter.bin").toFile().exists()) {
            return tmpIndi.toString();
        }
        return "libEFWFilter";
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
            eventPublisher.publishConnected(EquipmentType.FILTER_WHEEL, getDriverStatus());
        } catch (Throwable t) {
            log.error("Failed to load EFW driver", t);
            lastError.set(t.getMessage());
            loaded.set(false);
        }
    }

    private void loadLibrary() {
        if (lib != null) return;
        String libName = "EFWFilter";
        if (sdkPath != null && !sdkPath.equals("libEFWFilter")) {
            Path so = Path.of(sdkPath).resolve("libEFWFilter.so");
            Path bin = Path.of(sdkPath).resolve("libEFWFilter.bin");
            if (so.toFile().exists()) {
                lib = EfwLib.load(so.toAbsolutePath().toString());
            } else if (bin.toFile().exists()) {
                lib = EfwLib.load(bin.toAbsolutePath().toString());
            } else {
                throw new IllegalStateException("EFW SDK not found at " + sdkPath);
            }
        } else {
            lib = EfwLib.load(libName);
        }
    }

    @Override
    public void unload() {
        if (!loaded.getAndSet(false)) return;
        disconnect();
        lib = null;
        eventPublisher.publishDisconnected(EquipmentType.FILTER_WHEEL, "Profile unloaded");
    }

    @Override
    public boolean isLoaded() {
        return loaded.get();
    }

    @Override
    public List<LogicalDevice> getLogicalDevices() {
        if (!loaded.get() || lib == null) return List.of();
        int n = lib.EFWGetNum();
        if (n <= 0) return List.of();
        int connectedId = efwId.get();
        var devices = new ArrayList<LogicalDevice>();
        for (int i = 0; i < n; i++) {
            var idRef = new com.sun.jna.ptr.IntByReference();
            if (lib.EFWGetID(i, idRef) == EfwLib.EFW_SUCCESS) {
                int id = idRef.getValue();
                var info = new EfwInfo.ByReference();
                if (lib.EFWOpen(id) == EfwLib.EFW_SUCCESS) {
                    if (lib.EFWGetProperty(id, info) == EfwLib.EFW_SUCCESS) {
                        devices.add(new LogicalDevice(
                                info.getName(),
                                "03c3",
                                "120f",
                                EquipmentType.FILTER_WHEEL,
                                i));
                    }
                    if (id != connectedId) {
                        lib.EFWClose(id);
                    }
                }
            }
        }
        return devices;
    }

    @Override
    public FilterWheelStatus getStatus() {
        if (lib == null || !connected.get()) {
            return new FilterWheelStatus(0, false, slotCount.get());
        }
        int id = efwId.get();
        if (id < 0) return new FilterWheelStatus(0, false, slotCount.get());
        var posRef = new com.sun.jna.ptr.IntByReference();
        if (lib.EFWGetPosition(id, posRef) == EfwLib.EFW_SUCCESS) {
            int pos = posRef.getValue();
            boolean moving = (pos == EfwLib.EFW_IS_MOVING);
            return new FilterWheelStatus(moving ? 0 : pos, moving, slotCount.get());
        }
        return new FilterWheelStatus(0, false, slotCount.get());
    }

    @Override
    public FilterWheelConfiguration getConfiguration() {
        return configuration.get();
    }

    @Override
    public void setConfiguration(FilterWheelConfiguration config) {
        configuration.set(config);
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
    public FilterWheelDriverConfiguration getDriverConfiguration() {
        return driverConfig.get();
    }

    @Override
    public void setDriverConfiguration(FilterWheelDriverConfiguration config) {
        driverConfig.set(config);
    }

    @Override
    public void connect() {
        if (lib == null || !loaded.get()) return;
        if (connected.get()) return;
        lastError.set(null);
        int index = driverConfig.get().deviceIndex();
        int n = lib.EFWGetNum();
        if (n <= 0 || index >= n) {
            lastError.set("No EFW at index " + index);
            return;
        }
        var idRef = new com.sun.jna.ptr.IntByReference();
        if (lib.EFWGetID(index, idRef) != EfwLib.EFW_SUCCESS) {
            lastError.set("EFWGetID failed");
            return;
        }
        int id = idRef.getValue();
        if (lib.EFWOpen(id) != EfwLib.EFW_SUCCESS) {
            lastError.set("EFWOpen failed");
            return;
        }
        var info = new EfwInfo.ByReference();
        if (lib.EFWGetProperty(id, info) == EfwLib.EFW_SUCCESS) {
            slotCount.set(info.slotNum);
            syncFilterNamesToSlotCount(info.slotNum);
        }
        efwId.set(id);
        connected.set(true);
        eventPublisher.publishConnected(EquipmentType.FILTER_WHEEL, getDriverStatus());
        eventPublisher.publishStatusChanged(EquipmentType.FILTER_WHEEL, getStatus(), getDriverStatus());
    }

    private void syncFilterNamesToSlotCount(int slots) {
        FilterWheelConfiguration current = configuration.get();
        List<String> names = current.filterNames();
        if (names.size() == slots) return;
        var adjusted = new ArrayList<>(names);
        while (adjusted.size() < slots) {
            adjusted.add("Filter " + (adjusted.size() + 1));
        }
        if (adjusted.size() > slots) {
            adjusted = new ArrayList<>(adjusted.subList(0, slots));
        }
        configuration.set(new FilterWheelConfiguration(List.copyOf(adjusted)));
    }

    @Override
    public void disconnect() {
        if (!connected.getAndSet(false)) return;
        int id = efwId.getAndSet(-1);
        if (lib != null && id >= 0) {
            lib.EFWClose(id);
        }
        eventPublisher.publishDisconnected(EquipmentType.FILTER_WHEEL, "Disconnected");
    }

    @Override
    public void selectSlot(int slot) {
        if (lib == null || !connected.get()) return;
        int id = efwId.get();
        if (id < 0) return;
        if (slot < 0 || slot >= slotCount.get()) {
            log.warn("Slot {} out of range [0, {})", slot, slotCount.get());
            return;
        }
        int r = lib.EFWSetPosition(id, slot);
        if (r != EfwLib.EFW_SUCCESS) {
            String err = switch (r) {
                case EfwLib.EFW_ERROR_MOVING -> "EFW already moving";
                case EfwLib.EFW_ERROR_CLOSED -> "EFW closed";
                default -> "EFW error " + r;
            };
            log.warn("EFWSetPosition failed: {}", err);
            return;
        }
        eventPublisher.publishStatusChanged(EquipmentType.FILTER_WHEEL, getStatus(), getDriverStatus());
        moveCompletionExecutor.submit(() -> pollUntilMoveComplete(slot));
    }

    private void pollUntilMoveComplete(int targetSlot) {
        int id = efwId.get();
        if (id < 0 || lib == null || !connected.get()) return;
        var posRef = new com.sun.jna.ptr.IntByReference();
        try {
            while (connected.get() && lib != null) {
                if (lib.EFWGetPosition(id, posRef) != EfwLib.EFW_SUCCESS) break;
                int pos = posRef.getValue();
                if (pos != EfwLib.EFW_IS_MOVING) {
                    eventPublisher.publishStatusChanged(EquipmentType.FILTER_WHEEL,
                            new FilterWheelStatus(pos, false, slotCount.get()), getDriverStatus());
                    return;
                }
                eventPublisher.publishStatusChanged(EquipmentType.FILTER_WHEEL,
                        new FilterWheelStatus(0, true, slotCount.get()), getDriverStatus());
                Thread.sleep(300);
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
