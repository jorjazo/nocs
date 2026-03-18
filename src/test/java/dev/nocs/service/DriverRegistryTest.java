package dev.nocs.service;

import dev.nocs.domain.Driver;
import dev.nocs.domain.EquipmentType;
import dev.nocs.domain.LogicalDevice;
import dev.nocs.driver.EquipmentDriver;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;

class DriverRegistryTest {

    @Test
    void listDrivers_returnsAllDriverMetadata() {
        EquipmentDriver driver1 = stubDriver("driver.one", "Driver One");
        EquipmentDriver driver2 = stubDriver("driver.two", "Driver Two");
        DriverRegistry registry = new DriverRegistry(List.of(driver1, driver2));

        List<Driver> drivers = registry.listDrivers();

        assertThat(drivers).hasSize(2);
        assertThat(drivers).extracting(Driver::id).containsExactly("driver.one", "driver.two");
        assertThat(drivers).extracting(Driver::displayName).containsExactly("Driver One", "Driver Two");
    }

    @Test
    void listDrivers_emptyWhenNoDrivers() {
        DriverRegistry registry = new DriverRegistry(List.of());

        List<Driver> drivers = registry.listDrivers();

        assertThat(drivers).isEmpty();
    }

    @Test
    void getDriver_returnsDriverWhenFound() {
        EquipmentDriver driver = stubDriver("driver.one", "Driver One");
        DriverRegistry registry = new DriverRegistry(List.of(driver));

        Optional<Driver> result = registry.getDriver("driver.one");

        assertThat(result).isPresent();
        assertThat(result.get().id()).isEqualTo("driver.one");
        assertThat(result.get().displayName()).isEqualTo("Driver One");
    }

    @Test
    void getDriver_returnsEmptyWhenNotFound() {
        DriverRegistry registry = new DriverRegistry(List.of());

        Optional<Driver> result = registry.getDriver("nonexistent");

        assertThat(result).isEmpty();
    }

    @Test
    void listDevicesGroupedByType_groupsCorrectly() {
        LogicalDevice cam1 = new LogicalDevice("Cam1", "03c3:120e", EquipmentType.CAMERA, 0);
        LogicalDevice cam2 = new LogicalDevice("Cam2", "03c3:120e", EquipmentType.CAMERA, 1);
        LogicalDevice mount1 = new LogicalDevice("Mount1", "serial:1", EquipmentType.MOUNT, 0);
        EquipmentDriver driver = new EquipmentDriver() {
            @Override
            public Driver getMetadata() {
                return new Driver("test", "Test", "", "1.0", "", "", List.of());
            }

            @Override
            public List<LogicalDevice> getLogicalDevices() {
                return List.of(cam1, cam2, mount1);
            }
        };
        DriverRegistry registry = new DriverRegistry(List.of(driver));

        Map<EquipmentType, List<LogicalDevice>> grouped = registry.listDevicesGroupedByType();

        assertThat(grouped).containsKeys(EquipmentType.CAMERA, EquipmentType.MOUNT);
        assertThat(grouped.get(EquipmentType.CAMERA)).hasSize(2);
        assertThat(grouped.get(EquipmentType.MOUNT)).hasSize(1);
    }

    @Test
    void listDevices_filtersByEquipmentType() {
        LogicalDevice cam = new LogicalDevice("Cam", "03c3:120e", EquipmentType.CAMERA, 0);
        LogicalDevice mount = new LogicalDevice("Mount", "serial:1", EquipmentType.MOUNT, 0);
        EquipmentDriver driver = new EquipmentDriver() {
            @Override
            public Driver getMetadata() {
                return new Driver("test", "Test", "", "1.0", "", "", List.of());
            }

            @Override
            public List<LogicalDevice> getLogicalDevices() {
                return List.of(cam, mount);
            }
        };
        DriverRegistry registry = new DriverRegistry(List.of(driver));

        List<LogicalDevice> cameras = registry.listDevices(EquipmentType.CAMERA);

        assertThat(cameras).hasSize(1);
        assertThat(cameras.get(0).equipmentType()).isEqualTo(EquipmentType.CAMERA);
    }

    @Test
    void getDevice_returnsDeviceWhenFound() {
        LogicalDevice device = new LogicalDevice("Cam", "03c3:120e", EquipmentType.CAMERA, 0);
        EquipmentDriver driver = new EquipmentDriver() {
            @Override
            public Driver getMetadata() {
                return new Driver("test", "Test", "", "1.0", "", "", List.of());
            }

            @Override
            public List<LogicalDevice> getLogicalDevices() {
                return List.of(device);
            }
        };
        DriverRegistry registry = new DriverRegistry(List.of(driver));

        Optional<LogicalDevice> result = registry.getDevice(EquipmentType.CAMERA, "03c3:120e", 0);

        assertThat(result).isPresent();
        assertThat(result.get()).isEqualTo(device);
    }

    @Test
    void getDevice_returnsEmptyWhenNotFound() {
        DriverRegistry registry = new DriverRegistry(List.of());

        Optional<LogicalDevice> result = registry.getDevice(EquipmentType.CAMERA, "03c3:120e", 0);

        assertThat(result).isEmpty();
    }

    private static EquipmentDriver stubDriver(String id, String displayName) {
        return new EquipmentDriver() {
            @Override
            public Driver getMetadata() {
                return new Driver(id, displayName, "", "1.0", "", "", List.of());
            }

            @Override
            public List<LogicalDevice> getLogicalDevices() {
                return List.of();
            }
        };
    }
}
