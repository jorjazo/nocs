package dev.nocs.service;

import dev.nocs.domain.equipment.mount.MountConfiguration;
import dev.nocs.domain.equipment.mount.MountStatus;
import dev.nocs.driver.mount.MountSimulatorDriver;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class MountServiceTest {

    private MountService mountService;
    private DriverRegistry driverRegistry;

    @BeforeEach
    void setUp() {
        MountSimulatorDriver driver = new MountSimulatorDriver();
        driverRegistry = new DriverRegistry(List.of(driver));
        mountService = new MountService(driverRegistry);
    }

    @Test
    void getStatus_returnsEmpty_whenDriverNotLoaded() {
        assertThat(mountService.getStatus()).isEmpty();
    }

    @Test
    void getStatus_returnsStatus_whenDriverLoaded() {
        driverRegistry.loadDriver(MountSimulatorDriver.class.getCanonicalName());

        assertThat(mountService.getStatus()).isPresent();
        MountStatus status = mountService.getStatus().orElseThrow();
        assertThat(status.raHours()).isEqualTo(6.0);
        assertThat(status.decDegrees()).isEqualTo(45.0);
        assertThat(status.tracking()).isTrue();
    }

    @Test
    void getConfiguration_returnsConfig_whenDriverLoaded() {
        driverRegistry.loadDriver(MountSimulatorDriver.class.getCanonicalName());

        assertThat(mountService.getConfiguration()).isPresent();
        MountConfiguration config = mountService.getConfiguration().orElseThrow();
        assertThat(config.slewRateDegPerSec()).isEqualTo(2.0);
    }
}
