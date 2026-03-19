package dev.nocs.service;

import dev.nocs.domain.equipment.DriverStatus;
import dev.nocs.domain.equipment.camera.CameraConfiguration;
import dev.nocs.domain.equipment.camera.CameraDriverConfiguration;
import dev.nocs.domain.equipment.camera.CameraStatus;
import dev.nocs.driver.camera.CameraDriver;
import org.springframework.stereotype.Service;

import java.util.Optional;

/**
 * Service for camera operations. Delegates to the loaded camera driver.
 */
@Service
public class CameraService {

    private final DriverRegistry driverRegistry;
    private final ImageStorageService imageStorage;

    public CameraService(DriverRegistry driverRegistry, ImageStorageService imageStorage) {
        this.driverRegistry = driverRegistry;
        this.imageStorage = imageStorage;
    }

    public Optional<CameraStatus> getStatus() {
        return driverRegistry.getEquipmentDriver(CameraDriver.class).map(CameraDriver::getStatus);
    }

    public Optional<CameraConfiguration> getConfiguration() {
        return driverRegistry.getEquipmentDriver(CameraDriver.class).map(CameraDriver::getConfiguration);
    }

    public void setConfiguration(CameraConfiguration config) {
        driverRegistry.getEquipmentDriver(CameraDriver.class).ifPresent(d -> d.setConfiguration(config));
    }

    public Optional<DriverStatus> getDriverStatus() {
        return driverRegistry.getEquipmentDriver(CameraDriver.class).map(CameraDriver::getDriverStatus);
    }

    public Optional<CameraDriverConfiguration> getDriverConfiguration() {
        return driverRegistry.getEquipmentDriver(CameraDriver.class).map(CameraDriver::getDriverConfiguration);
    }

    public void setDriverConfiguration(CameraDriverConfiguration config) {
        driverRegistry.getEquipmentDriver(CameraDriver.class).ifPresent(d -> d.setDriverConfiguration(config));
    }

    public void connect() {
        driverRegistry.getEquipmentDriver(CameraDriver.class).ifPresent(CameraDriver::connect);
    }

    public void disconnect() {
        driverRegistry.getEquipmentDriver(CameraDriver.class).ifPresent(CameraDriver::disconnect);
    }

    public Optional<String> startExposure(double durationSeconds) {
        return driverRegistry.getEquipmentDriver(CameraDriver.class)
                .map(d -> d.startExposure(durationSeconds));
    }

    public Optional<byte[]> getImage(String frameId) {
        return driverRegistry.getEquipmentDriver(CameraDriver.class)
                .map(d -> d.getImage(frameId));
    }

    public byte[] getPreviewImage() {
        return imageStorage.getPreviewBytes();
    }

    public byte[] getFitsImage() {
        return imageStorage.getFitsBytes();
    }

    public boolean hasLatestImage() {
        return imageStorage.hasImage();
    }

    public ImageMetadata getLatestMetadata() {
        var stored = imageStorage.getLatest();
        return stored != null ? stored.metadata() : null;
    }
}
