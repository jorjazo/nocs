package dev.nocs.driver.simulator;

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
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Filter wheel simulator driver. Provides a simulated filter wheel device when loaded.
 */
@Component
public class FilterWheelSimulatorDriver implements EquipmentDriver, FilterWheelDriver {

    private static final Driver METADATA = new Driver(
            FilterWheelSimulatorDriver.class.getCanonicalName(),
            "Filter Wheel Simulator",
            "In-memory filter wheel simulator for development and testing",
            "1.0.0",
            "NOCS",
            "https://github.com/nocs",
            List.of("0000")
    );

    private static final LogicalDevice SIMULATED_FILTER_WHEEL =
            new LogicalDevice("Simulated Filter Wheel", "0000", "0004", EquipmentType.FILTER_WHEEL, 0);

    private static final List<String> DEFAULT_FILTERS = List.of("L", "R", "G", "B", "Ha", "SII", "OIII");

    private final AtomicBoolean loaded = new AtomicBoolean(false);
    private final AtomicInteger currentSlot = new AtomicInteger(0);
    private final AtomicBoolean moving = new AtomicBoolean(false);
    private final AtomicReference<FilterWheelConfiguration> configuration = new AtomicReference<>(
            new FilterWheelConfiguration(DEFAULT_FILTERS));
    private final AtomicReference<FilterWheelDriverConfiguration> driverConfig = new AtomicReference<>(
            new FilterWheelDriverConfiguration("simulator", ""));
    private final EquipmentEventPublisher eventPublisher;

    public FilterWheelSimulatorDriver(EquipmentEventPublisher eventPublisher) {
        this.eventPublisher = eventPublisher;
    }

    @Override
    public Driver getMetadata() {
        return METADATA;
    }

    @Override
    public void load() {
        loaded.set(true);
        eventPublisher.publishConnected(EquipmentType.FILTER_WHEEL, getDriverStatus());
        eventPublisher.publishStatusChanged(EquipmentType.FILTER_WHEEL, getStatus());
    }

    @Override
    public void unload() {
        loaded.set(false);
        eventPublisher.publishDisconnected(EquipmentType.FILTER_WHEEL, "Profile unloaded");
    }

    @Override
    public boolean isLoaded() {
        return loaded.get();
    }

    @Override
    public List<LogicalDevice> getLogicalDevices() {
        return loaded.get() ? List.of(SIMULATED_FILTER_WHEEL) : List.of();
    }

    @Override
    public FilterWheelStatus getStatus() {
        return new FilterWheelStatus(currentSlot.get(), moving.get(), configuration.get().filterNames().size());
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
        return loaded.get()
                ? new DriverStatus(DriverStatus.ConnectionState.CONNECTED, null)
                : new DriverStatus(DriverStatus.ConnectionState.DISCONNECTED, null);
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
        // Simulator: no-op when loaded
    }

    @Override
    public void disconnect() {
        // Simulator: no-op
    }

    @Override
    public void selectSlot(int slot) {
        int slotCount = configuration.get().filterNames().size();
        if (slot < 0 || slot >= slotCount) return;
        moving.set(true);
        eventPublisher.publishStatusChanged(EquipmentType.FILTER_WHEEL, getStatus());
        new Thread(() -> {
            try {
                Thread.sleep(200);
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
            currentSlot.set(slot);
            moving.set(false);
            eventPublisher.publishStatusChanged(EquipmentType.FILTER_WHEEL, getStatus());
        }).start();
    }
}
