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
 * driver metadata and logical devices.
 */
@Service
public class DriverRegistry {

    private final List<EquipmentDriver> drivers;

    public DriverRegistry(List<EquipmentDriver> drivers) {
        this.drivers = drivers != null ? drivers : List.of();
    }

    /**
     * List all available drivers.
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
     * List all logical devices, grouped by equipment type.
     */
    public Map<EquipmentType, List<LogicalDevice>> listDevicesGroupedByType() {
        return drivers.stream()
                .flatMap(d -> d.getLogicalDevices().stream())
                .collect(Collectors.groupingBy(LogicalDevice::equipmentType));
    }

    /**
     * List logical devices for an equipment type.
     */
    public List<LogicalDevice> listDevices(EquipmentType equipmentType) {
        return drivers.stream()
                .flatMap(d -> d.getLogicalDevices().stream())
                .filter(ld -> ld.equipmentType() == equipmentType)
                .toList();
    }

    /**
     * Get a logical device by equipment type, hardware id, and index.
     */
    public Optional<LogicalDevice> getDevice(EquipmentType equipmentType, String hwId, int index) {
        return drivers.stream()
                .flatMap(d -> d.getLogicalDevices().stream())
                .filter(ld -> ld.equipmentType() == equipmentType
                        && ld.hardwareId().equals(hwId)
                        && ld.index() == index)
                .findFirst();
    }
}
