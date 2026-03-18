package dev.nocs.service;

import dev.nocs.domain.equipment.DriverStatus;
import dev.nocs.domain.equipment.filterwheel.FilterWheelConfiguration;
import dev.nocs.domain.equipment.filterwheel.FilterWheelDriverConfiguration;
import dev.nocs.domain.equipment.filterwheel.FilterWheelStatus;
import dev.nocs.driver.filterwheel.FilterWheelDriver;
import org.springframework.stereotype.Service;

import java.util.Optional;

/**
 * Service for filter wheel operations. Delegates to the loaded filter wheel driver.
 */
@Service
public class FilterWheelService {

    private final DriverRegistry driverRegistry;

    public FilterWheelService(DriverRegistry driverRegistry) {
        this.driverRegistry = driverRegistry;
    }

    public Optional<FilterWheelStatus> getStatus() {
        return driverRegistry.getEquipmentDriver(FilterWheelDriver.class).map(FilterWheelDriver::getStatus);
    }

    public Optional<FilterWheelConfiguration> getConfiguration() {
        return driverRegistry.getEquipmentDriver(FilterWheelDriver.class).map(FilterWheelDriver::getConfiguration);
    }

    public void setConfiguration(FilterWheelConfiguration config) {
        driverRegistry.getEquipmentDriver(FilterWheelDriver.class).ifPresent(d -> d.setConfiguration(config));
    }

    public Optional<DriverStatus> getDriverStatus() {
        return driverRegistry.getEquipmentDriver(FilterWheelDriver.class).map(FilterWheelDriver::getDriverStatus);
    }

    public Optional<FilterWheelDriverConfiguration> getDriverConfiguration() {
        return driverRegistry.getEquipmentDriver(FilterWheelDriver.class).map(FilterWheelDriver::getDriverConfiguration);
    }

    public void setDriverConfiguration(FilterWheelDriverConfiguration config) {
        driverRegistry.getEquipmentDriver(FilterWheelDriver.class).ifPresent(d -> d.setDriverConfiguration(config));
    }

    public void connect() {
        driverRegistry.getEquipmentDriver(FilterWheelDriver.class).ifPresent(FilterWheelDriver::connect);
    }

    public void disconnect() {
        driverRegistry.getEquipmentDriver(FilterWheelDriver.class).ifPresent(FilterWheelDriver::disconnect);
    }

    public void selectSlot(int slot) {
        driverRegistry.getEquipmentDriver(FilterWheelDriver.class).ifPresent(d -> d.selectSlot(slot));
    }
}
