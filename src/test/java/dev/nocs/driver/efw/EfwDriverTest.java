package dev.nocs.driver.efw;

import dev.nocs.domain.Driver;
import dev.nocs.domain.EquipmentType;
import dev.nocs.domain.LogicalDevice;
import dev.nocs.domain.equipment.DriverStatus;
import dev.nocs.domain.equipment.filterwheel.FilterWheelConfiguration;
import dev.nocs.domain.equipment.filterwheel.FilterWheelDriverConfiguration;
import dev.nocs.domain.equipment.filterwheel.FilterWheelStatus;
import dev.nocs.events.EquipmentEventPublisher;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

class EfwDriverTest {

    private final EquipmentEventPublisher eventPublisher = mock(EquipmentEventPublisher.class);

    @Test
    void getMetadata_returnsZwoEfwDriverInfo() {
        EfwDriver driver = new EfwDriver(eventPublisher, "/nonexistent/path");

        Driver meta = driver.getMetadata();

        assertThat(meta.id()).isEqualTo(EfwDriver.class.getCanonicalName());
        assertThat(meta.displayName()).isEqualTo("ZWO EFW");
        assertThat(meta.supportedVendorIds()).containsExactly("03c3");
    }

    @Test
    void whenNotLoaded_getLogicalDevices_returnsEmpty() {
        EfwDriver driver = new EfwDriver(eventPublisher, "/nonexistent/path");

        List<LogicalDevice> devices = driver.getLogicalDevices();

        assertThat(devices).isEmpty();
    }

    @Test
    void whenNotLoaded_getDriverStatus_returnsDisconnected() {
        EfwDriver driver = new EfwDriver(eventPublisher, "/nonexistent/path");

        DriverStatus status = driver.getDriverStatus();

        assertThat(status.connectionState()).isEqualTo(DriverStatus.ConnectionState.DISCONNECTED);
    }

    @Test
    void whenNotConnected_getStatus_returnsDefaultValues() {
        EfwDriver driver = new EfwDriver(eventPublisher, "/nonexistent/path");

        FilterWheelStatus status = driver.getStatus();

        assertThat(status.currentSlot()).isZero();
        assertThat(status.moving()).isFalse();
        assertThat(status.slotCount()).isEqualTo(7);
    }

    @Test
    void load_withInvalidPath_setsErrorAndRemainsUnloaded() {
        EfwDriver driver = new EfwDriver(eventPublisher, "/nonexistent/path/that/does/not/exist");

        driver.load();

        assertThat(driver.isLoaded()).isFalse();
        assertThat(driver.getDriverStatus().lastError()).isNotNull();
    }

    @Test
    void unload_whenNotLoaded_isNoOp() {
        EfwDriver driver = new EfwDriver(eventPublisher, "/nonexistent/path");

        driver.unload();

        assertThat(driver.isLoaded()).isFalse();
    }

    @Test
    void getDriverConfiguration_returnsDefaultEfwConfig() {
        EfwDriver driver = new EfwDriver(eventPublisher, "/nonexistent/path");

        FilterWheelDriverConfiguration config = driver.getDriverConfiguration();

        assertThat(config.driverType()).isEqualTo("efw");
        assertThat(config.deviceIndex()).isZero();
    }

    @Test
    void setDriverConfiguration_updatesConfig() {
        EfwDriver driver = new EfwDriver(eventPublisher, "/nonexistent/path");
        var newConfig = new FilterWheelDriverConfiguration("efw", "/dev/ttyUSB0", 1);

        driver.setDriverConfiguration(newConfig);

        assertThat(driver.getDriverConfiguration().deviceIndex()).isEqualTo(1);
        assertThat(driver.getDriverConfiguration().serialPort()).isEqualTo("/dev/ttyUSB0");
    }

    @Test
    void setConfiguration_updatesFilterNames() {
        EfwDriver driver = new EfwDriver(eventPublisher, "/nonexistent/path");
        var newConfig = new FilterWheelConfiguration(List.of("Ha", "OIII", "SII", "L", "R"));

        driver.setConfiguration(newConfig);

        assertThat(driver.getConfiguration().filterNames()).containsExactly("Ha", "OIII", "SII", "L", "R");
    }

    @Test
    void connect_whenNotLoaded_isNoOp() {
        EfwDriver driver = new EfwDriver(eventPublisher, "/nonexistent/path");

        driver.connect();

        assertThat(driver.getDriverStatus().connectionState())
                .isEqualTo(DriverStatus.ConnectionState.DISCONNECTED);
    }

    @Test
    void disconnect_whenNotConnected_isNoOp() {
        EfwDriver driver = new EfwDriver(eventPublisher, "/nonexistent/path");

        driver.disconnect();

        assertThat(driver.getDriverStatus().connectionState())
                .isEqualTo(DriverStatus.ConnectionState.DISCONNECTED);
    }

    @Test
    void selectSlot_whenNotConnected_isNoOp() {
        EfwDriver driver = new EfwDriver(eventPublisher, "/nonexistent/path");

        driver.selectSlot(3);

        assertThat(driver.getStatus().currentSlot()).isZero();
        assertThat(driver.getStatus().moving()).isFalse();
    }
}
