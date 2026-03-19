package dev.nocs.driver.asi;

import dev.nocs.domain.Driver;
import dev.nocs.domain.EquipmentType;
import dev.nocs.domain.LogicalDevice;
import dev.nocs.domain.equipment.DriverStatus;
import dev.nocs.domain.equipment.camera.CameraConfiguration;
import dev.nocs.domain.equipment.camera.CameraDriverConfiguration;
import dev.nocs.domain.equipment.camera.CameraStatus;
import dev.nocs.events.EquipmentEventPublisher;
import dev.nocs.service.ImageStorageService;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

class AsiDriverTest {

    private final EquipmentEventPublisher eventPublisher = mock(EquipmentEventPublisher.class);
    private final ImageStorageService imageStorage = mock(ImageStorageService.class);

    @Test
    void getMetadata_returnsZwoAsiDriverInfo() {
        AsiDriver driver = new AsiDriver(eventPublisher, imageStorage, "/nonexistent/path");

        Driver meta = driver.getMetadata();

        assertThat(meta.id()).isEqualTo(AsiDriver.class.getCanonicalName());
        assertThat(meta.displayName()).isEqualTo("ZWO ASI Camera");
        assertThat(meta.manufacturer()).isEqualTo("ZWO");
        assertThat(meta.supportedVendorIds()).containsExactly("03c3");
    }

    @Test
    void whenNotLoaded_getLogicalDevices_returnsEmpty() {
        AsiDriver driver = new AsiDriver(eventPublisher, imageStorage, "/nonexistent/path");

        List<LogicalDevice> devices = driver.getLogicalDevices();

        assertThat(devices).isEmpty();
    }

    @Test
    void whenNotLoaded_getDriverStatus_returnsDisconnected() {
        AsiDriver driver = new AsiDriver(eventPublisher, imageStorage, "/nonexistent/path");

        DriverStatus status = driver.getDriverStatus();

        assertThat(status.connectionState()).isEqualTo(DriverStatus.ConnectionState.DISCONNECTED);
    }

    @Test
    void whenNotConnected_getStatus_returnsDefaultValues() {
        AsiDriver driver = new AsiDriver(eventPublisher, imageStorage, "/nonexistent/path");

        CameraStatus status = driver.getStatus();

        assertThat(status.exposing()).isFalse();
        assertThat(status.temperatureCelsius()).isEqualTo(20.0);
        assertThat(status.currentFrameId()).isEmpty();
    }

    @Test
    void load_withInvalidPath_setsErrorAndRemainsUnloaded() {
        AsiDriver driver = new AsiDriver(eventPublisher, imageStorage, "/nonexistent/path/that/does/not/exist");

        driver.load();

        assertThat(driver.isLoaded()).isFalse();
        assertThat(driver.getDriverStatus().lastError()).isNotNull();
    }

    @Test
    void unload_whenNotLoaded_isNoOp() {
        AsiDriver driver = new AsiDriver(eventPublisher, imageStorage, "/nonexistent/path");

        driver.unload();

        assertThat(driver.isLoaded()).isFalse();
    }

    @Test
    void getDriverConfiguration_returnsDefaultAsiConfig() {
        AsiDriver driver = new AsiDriver(eventPublisher, imageStorage, "/nonexistent/path");

        CameraDriverConfiguration config = driver.getDriverConfiguration();

        assertThat(config.driverType()).isEqualTo("asi");
        assertThat(config.cameraIndex()).isZero();
    }

    @Test
    void setDriverConfiguration_updatesConfig() {
        AsiDriver driver = new AsiDriver(eventPublisher, imageStorage, "/nonexistent/path");
        var newConfig = new CameraDriverConfiguration("asi", 1);

        driver.setDriverConfiguration(newConfig);

        assertThat(driver.getDriverConfiguration().cameraIndex()).isEqualTo(1);
        assertThat(driver.getDriverConfiguration().driverType()).isEqualTo("asi");
    }

    @Test
    void setConfiguration_updatesGainOffsetBinning() {
        AsiDriver driver = new AsiDriver(eventPublisher, imageStorage, "/nonexistent/path");
        var newConfig = new CameraConfiguration(139, 21, 2, 0, 0, 2328, 1760);

        driver.setConfiguration(newConfig);

        CameraConfiguration cfg = driver.getConfiguration();
        assertThat(cfg.gain()).isEqualTo(139);
        assertThat(cfg.offset()).isEqualTo(21);
        assertThat(cfg.binning()).isEqualTo(2);
        assertThat(cfg.roiWidth()).isEqualTo(2328);
        assertThat(cfg.roiHeight()).isEqualTo(1760);
    }

    @Test
    void connect_whenNotLoaded_isNoOp() {
        AsiDriver driver = new AsiDriver(eventPublisher, imageStorage, "/nonexistent/path");

        driver.connect();

        assertThat(driver.getDriverStatus().connectionState())
                .isEqualTo(DriverStatus.ConnectionState.DISCONNECTED);
    }

    @Test
    void disconnect_whenNotConnected_isNoOp() {
        AsiDriver driver = new AsiDriver(eventPublisher, imageStorage, "/nonexistent/path");

        driver.disconnect();

        assertThat(driver.getDriverStatus().connectionState())
                .isEqualTo(DriverStatus.ConnectionState.DISCONNECTED);
    }

    @Test
    void getImage_withUnknownFrameId_returnsEmptyArray() {
        AsiDriver driver = new AsiDriver(eventPublisher, imageStorage, "/nonexistent/path");

        byte[] data = driver.getImage("nonexistent-frame");

        assertThat(data).isEmpty();
    }

    @Test
    void getConfiguration_returnsDefaultValues() {
        AsiDriver driver = new AsiDriver(eventPublisher, imageStorage, "/nonexistent/path");

        CameraConfiguration cfg = driver.getConfiguration();

        assertThat(cfg.gain()).isZero();
        assertThat(cfg.offset()).isEqualTo(10);
        assertThat(cfg.binning()).isEqualTo(1);
        assertThat(cfg.roiWidth()).isEqualTo(4656);
        assertThat(cfg.roiHeight()).isEqualTo(3520);
    }
}
