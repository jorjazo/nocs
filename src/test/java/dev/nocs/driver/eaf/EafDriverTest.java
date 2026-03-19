package dev.nocs.driver.eaf;

import dev.nocs.domain.Driver;
import dev.nocs.domain.EquipmentType;
import dev.nocs.domain.LogicalDevice;
import dev.nocs.domain.equipment.DriverStatus;
import dev.nocs.domain.equipment.focuser.FocuserDriverConfiguration;
import dev.nocs.domain.equipment.focuser.FocuserStatus;
import dev.nocs.events.EquipmentEventPublisher;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

class EafDriverTest {

    private final EquipmentEventPublisher eventPublisher = mock(EquipmentEventPublisher.class);

    @Test
    void getMetadata_returnsZwoEafDriverInfo() {
        EafDriver driver = new EafDriver(eventPublisher, "/nonexistent/path");

        Driver meta = driver.getMetadata();

        assertThat(meta.id()).isEqualTo(EafDriver.class.getCanonicalName());
        assertThat(meta.displayName()).isEqualTo("ZWO EAF");
        assertThat(meta.supportedVendorIds()).containsExactly("03c3");
    }

    @Test
    void whenNotLoaded_getLogicalDevices_returnsEmpty() {
        EafDriver driver = new EafDriver(eventPublisher, "/nonexistent/path");

        List<LogicalDevice> devices = driver.getLogicalDevices();

        assertThat(devices).isEmpty();
    }

    @Test
    void whenNotLoaded_getDriverStatus_returnsDisconnected() {
        EafDriver driver = new EafDriver(eventPublisher, "/nonexistent/path");

        DriverStatus status = driver.getDriverStatus();

        assertThat(status.connectionState()).isEqualTo(DriverStatus.ConnectionState.DISCONNECTED);
    }

    @Test
    void whenNotConnected_getStatus_returnsDefaultValues() {
        EafDriver driver = new EafDriver(eventPublisher, "/nonexistent/path");

        FocuserStatus status = driver.getStatus();

        assertThat(status.position()).isZero();
        assertThat(status.moving()).isFalse();
        assertThat(status.temperatureCelsius()).isEqualTo(20.0);
    }

    @Test
    void load_withInvalidPath_setsErrorAndRemainsUnloaded() {
        EafDriver driver = new EafDriver(eventPublisher, "/nonexistent/path/that/does/not/exist");

        driver.load();

        assertThat(driver.isLoaded()).isFalse();
        assertThat(driver.getDriverStatus().lastError()).isNotNull();
    }

    @Test
    void unload_whenNotLoaded_isNoOp() {
        EafDriver driver = new EafDriver(eventPublisher, "/nonexistent/path");

        driver.unload();

        assertThat(driver.isLoaded()).isFalse();
    }

    @Test
    void getDriverConfiguration_returnsDefaultEafConfig() {
        EafDriver driver = new EafDriver(eventPublisher, "/nonexistent/path");

        FocuserDriverConfiguration config = driver.getDriverConfiguration();

        assertThat(config.driverType()).isEqualTo("eaf");
        assertThat(config.deviceIndex()).isZero();
    }
}
