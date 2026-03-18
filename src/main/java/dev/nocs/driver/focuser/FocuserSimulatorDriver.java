package dev.nocs.driver.focuser;

import dev.nocs.domain.Driver;
import dev.nocs.domain.EquipmentType;
import dev.nocs.domain.LogicalDevice;
import dev.nocs.domain.equipment.DriverStatus;
import dev.nocs.domain.equipment.focuser.FocuserConfiguration;
import dev.nocs.domain.equipment.focuser.FocuserDriverConfiguration;
import dev.nocs.domain.equipment.focuser.FocuserStatus;
import dev.nocs.driver.EquipmentDriver;
import dev.nocs.events.EquipmentEventPublisher;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Focuser simulator driver. Provides a simulated focuser device when loaded.
 */
@Component
public class FocuserSimulatorDriver implements EquipmentDriver, FocuserDriver {

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
    private final AtomicInteger position = new AtomicInteger(25000);
    private final AtomicBoolean moving = new AtomicBoolean(false);
    private final AtomicReference<FocuserConfiguration> configuration = new AtomicReference<>(
            new FocuserConfiguration(50000, 1));
    private final AtomicReference<FocuserDriverConfiguration> driverConfig = new AtomicReference<>(
            new FocuserDriverConfiguration("simulator", ""));
    private final EquipmentEventPublisher eventPublisher;

    public FocuserSimulatorDriver(EquipmentEventPublisher eventPublisher) {
        this.eventPublisher = eventPublisher;
    }

    @Override
    public Driver getMetadata() {
        return METADATA;
    }

    @Override
    public void load() {
        loaded.set(true);
        eventPublisher.publishConnected(EquipmentType.FOCUSER, getDriverStatus());
        eventPublisher.publishStatusChanged(EquipmentType.FOCUSER, getStatus());
    }

    @Override
    public void unload() {
        loaded.set(false);
        eventPublisher.publishDisconnected(EquipmentType.FOCUSER, "Profile unloaded");
    }

    @Override
    public boolean isLoaded() {
        return loaded.get();
    }

    @Override
    public List<LogicalDevice> getLogicalDevices() {
        return loaded.get() ? List.of(SIMULATED_FOCUSER) : List.of();
    }

    @Override
    public FocuserStatus getStatus() {
        return new FocuserStatus(position.get(), moving.get(), 20.0);
    }

    @Override
    public FocuserConfiguration getConfiguration() {
        return configuration.get();
    }

    @Override
    public void setConfiguration(FocuserConfiguration config) {
        configuration.set(config);
    }

    @Override
    public DriverStatus getDriverStatus() {
        return loaded.get()
                ? new DriverStatus(DriverStatus.ConnectionState.CONNECTED, null)
                : new DriverStatus(DriverStatus.ConnectionState.DISCONNECTED, null);
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
        // Simulator: no-op when loaded
    }

    @Override
    public void disconnect() {
        // Simulator: no-op
    }

    @Override
    public void moveRelative(int steps) {
        int target = Math.max(0, Math.min(position.get() + steps, configuration.get().maxPosition()));
        moveTo(target);
    }

    @Override
    public void moveAbsolute(int targetPosition) {
        int clamped = Math.max(0, Math.min(targetPosition, configuration.get().maxPosition()));
        moveTo(clamped);
    }

    private void moveTo(int target) {
        moving.set(true);
        eventPublisher.publishStatusChanged(EquipmentType.FOCUSER, getStatus());
        new Thread(() -> {
            try {
                Thread.sleep(500);
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
            position.set(target);
            moving.set(false);
            eventPublisher.publishStatusChanged(EquipmentType.FOCUSER, getStatus());
        }).start();
    }
}
