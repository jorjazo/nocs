package dev.nocs.service;

import dev.nocs.domain.Driver;
import dev.nocs.domain.EquipmentType;
import dev.nocs.domain.LogicalDevice;
import dev.nocs.driver.EquipmentDriver;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Collectors;

/**
 * Registry of equipment drivers. Discovers and provides access to
 * driver metadata and logical devices. Only loaded drivers provide devices.
 */
@Service
public class DriverRegistry {

    private final List<EquipmentDriver> drivers;

    public DriverRegistry(List<EquipmentDriver> drivers) {
        this.drivers = drivers != null ? drivers : List.of();
    }

    /**
     * List all available drivers (metadata only).
     */
    public List<Driver> listDrivers() {
        return drivers.stream()
                .map(EquipmentDriver::getMetadata)
                .toList();
    }

    /**
     * Get a driver by id (canonical class name).
     */
    public Optional<Driver> getDriver(String driverId) {
        return drivers.stream()
                .filter(d -> d.getMetadata().id().equals(driverId))
                .map(EquipmentDriver::getMetadata)
                .findFirst();
    }

    /**
     * Load a driver by id.
     */
    public void loadDriver(String driverId) {
        findDriver(driverId).ifPresent(EquipmentDriver::load);
    }

    /**
     * Unload a driver by id.
     */
    public void unloadDriver(String driverId) {
        findDriver(driverId).ifPresent(EquipmentDriver::unload);
    }

    /**
     * Unload all drivers.
     */
    public void unloadAll() {
        drivers.forEach(EquipmentDriver::unload);
    }

    /**
     * List all logical devices from loaded drivers, grouped by equipment type.
     */
    public Map<EquipmentType, List<LogicalDevice>> listDevicesGroupedByType() {
        return drivers.stream()
                .filter(EquipmentDriver::isLoaded)
                .flatMap(d -> d.getLogicalDevices().stream())
                .collect(Collectors.groupingBy(LogicalDevice::equipmentType));
    }

    /**
     * List logical devices for an equipment type (from loaded drivers only).
     */
    public List<LogicalDevice> listDevices(EquipmentType equipmentType) {
        return drivers.stream()
                .filter(EquipmentDriver::isLoaded)
                .flatMap(d -> d.getLogicalDevices().stream())
                .filter(ld -> ld.equipmentType() == equipmentType)
                .toList();
    }

    /**
     * Get a logical device by equipment type, vendor id, product id, and index.
     */
    public Optional<LogicalDevice> getDevice(EquipmentType equipmentType, String vendorId, String productId, int index) {
        return drivers.stream()
                .filter(EquipmentDriver::isLoaded)
                .flatMap(d -> d.getLogicalDevices().stream())
                .filter(ld -> ld.equipmentType() == equipmentType
                        && ld.vendorId().equals(vendorId)
                        && ld.productId().equals(productId)
                        && ld.index() == index)
                .findFirst();
    }

    private Optional<EquipmentDriver> findDriver(String driverId) {
        return drivers.stream()
                .filter(d -> d.getMetadata().id().equals(driverId))
                .findFirst();
    }
}
