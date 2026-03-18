package dev.nocs.service;

import dev.nocs.domain.equipment.DriverStatus;
import dev.nocs.domain.equipment.mount.MountConfiguration;
import dev.nocs.domain.equipment.mount.MountDriverConfiguration;
import dev.nocs.domain.equipment.mount.MountStatus;
import dev.nocs.driver.mount.MountDriver;
import org.springframework.stereotype.Service;

import java.util.Optional;

/**
 * Service for mount operations. Delegates to the loaded mount driver.
 */
@Service
public class MountService {

    private final DriverRegistry driverRegistry;

    public MountService(DriverRegistry driverRegistry) {
        this.driverRegistry = driverRegistry;
    }

    public Optional<MountStatus> getStatus() {
        return driverRegistry.getEquipmentDriver(MountDriver.class).map(MountDriver::getStatus);
    }

    public Optional<MountConfiguration> getConfiguration() {
        return driverRegistry.getEquipmentDriver(MountDriver.class).map(MountDriver::getConfiguration);
    }

    public void setConfiguration(MountConfiguration config) {
        driverRegistry.getEquipmentDriver(MountDriver.class).ifPresent(d -> d.setConfiguration(config));
    }

    public Optional<DriverStatus> getDriverStatus() {
        return driverRegistry.getEquipmentDriver(MountDriver.class).map(MountDriver::getDriverStatus);
    }

    public Optional<MountDriverConfiguration> getDriverConfiguration() {
        return driverRegistry.getEquipmentDriver(MountDriver.class).map(MountDriver::getDriverConfiguration);
    }

    public void setDriverConfiguration(MountDriverConfiguration config) {
        driverRegistry.getEquipmentDriver(MountDriver.class).ifPresent(d -> d.setDriverConfiguration(config));
    }

    public void connect() {
        driverRegistry.getEquipmentDriver(MountDriver.class).ifPresent(MountDriver::connect);
    }

    public void disconnect() {
        driverRegistry.getEquipmentDriver(MountDriver.class).ifPresent(MountDriver::disconnect);
    }

    public void gotoPosition(double raHours, double decDegrees) {
        driverRegistry.getEquipmentDriver(MountDriver.class).ifPresent(d -> d.gotoPosition(raHours, decDegrees));
    }

    public void park() {
        driverRegistry.getEquipmentDriver(MountDriver.class).ifPresent(MountDriver::park);
    }

    public void sync(double raHours, double decDegrees) {
        driverRegistry.getEquipmentDriver(MountDriver.class).ifPresent(d -> d.sync(raHours, decDegrees));
    }

    public void startTracking() {
        driverRegistry.getEquipmentDriver(MountDriver.class).ifPresent(MountDriver::startTracking);
    }

    public void stopTracking() {
        driverRegistry.getEquipmentDriver(MountDriver.class).ifPresent(MountDriver::stopTracking);
    }
}
