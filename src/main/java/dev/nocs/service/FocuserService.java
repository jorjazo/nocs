package dev.nocs.service;

import dev.nocs.domain.equipment.DriverStatus;
import dev.nocs.domain.equipment.focuser.FocuserConfiguration;
import dev.nocs.domain.equipment.focuser.FocuserDriverConfiguration;
import dev.nocs.domain.equipment.focuser.FocuserStatus;
import dev.nocs.driver.focuser.FocuserDriver;
import org.springframework.stereotype.Service;

import java.util.Optional;

/**
 * Service for focuser operations. Delegates to the loaded focuser driver.
 */
@Service
public class FocuserService {

    private final DriverRegistry driverRegistry;

    public FocuserService(DriverRegistry driverRegistry) {
        this.driverRegistry = driverRegistry;
    }

    public Optional<FocuserStatus> getStatus() {
        return driverRegistry.getEquipmentDriver(FocuserDriver.class).map(FocuserDriver::getStatus);
    }

    public Optional<FocuserConfiguration> getConfiguration() {
        return driverRegistry.getEquipmentDriver(FocuserDriver.class).map(FocuserDriver::getConfiguration);
    }

    public void setConfiguration(FocuserConfiguration config) {
        driverRegistry.getEquipmentDriver(FocuserDriver.class).ifPresent(d -> d.setConfiguration(config));
    }

    public Optional<DriverStatus> getDriverStatus() {
        return driverRegistry.getEquipmentDriver(FocuserDriver.class).map(FocuserDriver::getDriverStatus);
    }

    public Optional<FocuserDriverConfiguration> getDriverConfiguration() {
        return driverRegistry.getEquipmentDriver(FocuserDriver.class).map(FocuserDriver::getDriverConfiguration);
    }

    public void setDriverConfiguration(FocuserDriverConfiguration config) {
        driverRegistry.getEquipmentDriver(FocuserDriver.class).ifPresent(d -> d.setDriverConfiguration(config));
    }

    public void connect() {
        driverRegistry.getEquipmentDriver(FocuserDriver.class).ifPresent(FocuserDriver::connect);
    }

    public void disconnect() {
        driverRegistry.getEquipmentDriver(FocuserDriver.class).ifPresent(FocuserDriver::disconnect);
    }

    public void moveRelative(int steps) {
        driverRegistry.getEquipmentDriver(FocuserDriver.class).ifPresent(d -> d.moveRelative(steps));
    }

    public void moveAbsolute(int position) {
        driverRegistry.getEquipmentDriver(FocuserDriver.class).ifPresent(d -> d.moveAbsolute(position));
    }
}
