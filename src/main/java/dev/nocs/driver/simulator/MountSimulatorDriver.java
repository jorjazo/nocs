package dev.nocs.driver.simulator;

import dev.nocs.domain.Driver;
import dev.nocs.domain.EquipmentType;
import dev.nocs.domain.LogicalDevice;
import dev.nocs.domain.equipment.DriverStatus;
import dev.nocs.domain.equipment.mount.MountConfiguration;
import dev.nocs.domain.equipment.mount.MountDriverConfiguration;
import dev.nocs.domain.equipment.mount.MountStatus;
import dev.nocs.driver.EquipmentDriver;
import dev.nocs.driver.mount.MountDriver;
import dev.nocs.events.EquipmentEventPublisher;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Mount simulator driver. Provides a simulated mount device when loaded.
 */
@Component
public class MountSimulatorDriver implements EquipmentDriver, MountDriver {

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
    private final AtomicReference<MountStatus> status = new AtomicReference<>(
            new MountStatus(6.0, 45.0, true, false, false));
    private final AtomicReference<MountConfiguration> configuration = new AtomicReference<>(
            new MountConfiguration(2.0, 0.5, true, 5.0));
    private final AtomicReference<MountDriverConfiguration> driverConfig = new AtomicReference<>(
            new MountDriverConfiguration("simulator", "", 4030, ""));
    private final AtomicBoolean slewing = new AtomicBoolean(false);
    private final AtomicBoolean parked = new AtomicBoolean(false);
    private final EquipmentEventPublisher eventPublisher;

    public MountSimulatorDriver(EquipmentEventPublisher eventPublisher) {
        this.eventPublisher = eventPublisher;
    }

    @Override
    public Driver getMetadata() {
        return METADATA;
    }

    @Override
    public void load() {
        loaded.set(true);
        eventPublisher.publishConnected(EquipmentType.MOUNT, getDriverStatus());
        eventPublisher.publishStatusChanged(EquipmentType.MOUNT, status.get());
    }

    @Override
    public void unload() {
        loaded.set(false);
        eventPublisher.publishDisconnected(EquipmentType.MOUNT, "Profile unloaded");
    }

    @Override
    public boolean isLoaded() {
        return loaded.get();
    }

    @Override
    public List<LogicalDevice> getLogicalDevices() {
        return loaded.get() ? List.of(SIMULATED_MOUNT) : List.of();
    }

    @Override
    public MountStatus getStatus() {
        return status.get();
    }

    @Override
    public MountConfiguration getConfiguration() {
        return configuration.get();
    }

    @Override
    public void setConfiguration(MountConfiguration config) {
        configuration.set(config);
    }

    @Override
    public DriverStatus getDriverStatus() {
        return loaded.get()
                ? new DriverStatus(DriverStatus.ConnectionState.CONNECTED, null)
                : new DriverStatus(DriverStatus.ConnectionState.DISCONNECTED, null);
    }

    @Override
    public MountDriverConfiguration getDriverConfiguration() {
        return driverConfig.get();
    }

    @Override
    public void setDriverConfiguration(MountDriverConfiguration config) {
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
    public void gotoPosition(double raHours, double decDegrees) {
        slewing.set(true);
        status.set(new MountStatus(raHours, decDegrees, status.get().tracking(), true, false));
        parked.set(false);
        eventPublisher.publishStatusChanged(EquipmentType.MOUNT, status.get());
        // Simulate slew completion
        new Thread(() -> {
            try {
                Thread.sleep(2000);
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
            slewing.set(false);
            status.set(new MountStatus(raHours, decDegrees, status.get().tracking(), false, false));
            eventPublisher.publishStatusChanged(EquipmentType.MOUNT, status.get());
        }).start();
    }

    @Override
    public void park() {
        slewing.set(true);
        status.set(new MountStatus(0, 90, false, true, false));
        eventPublisher.publishStatusChanged(EquipmentType.MOUNT, status.get());
        new Thread(() -> {
            try {
                Thread.sleep(1500);
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
            slewing.set(false);
            parked.set(true);
            status.set(new MountStatus(0, 90, false, false, true));
            eventPublisher.publishStatusChanged(EquipmentType.MOUNT, status.get());
        }).start();
    }

    @Override
    public void sync(double raHours, double decDegrees) {
        status.set(new MountStatus(raHours, decDegrees, status.get().tracking(), false, false));
        eventPublisher.publishStatusChanged(EquipmentType.MOUNT, status.get());
    }

    @Override
    public void startTracking() {
        MountStatus s = status.get();
        status.set(new MountStatus(s.raHours(), s.decDegrees(), true, s.slewing(), s.parked()));
        eventPublisher.publishStatusChanged(EquipmentType.MOUNT, status.get());
    }

    @Override
    public void stopTracking() {
        MountStatus s = status.get();
        status.set(new MountStatus(s.raHours(), s.decDegrees(), false, s.slewing(), s.parked()));
        eventPublisher.publishStatusChanged(EquipmentType.MOUNT, status.get());
    }
}
