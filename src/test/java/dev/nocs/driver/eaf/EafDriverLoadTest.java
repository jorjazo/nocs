package dev.nocs.driver.eaf;

import dev.nocs.domain.LogicalDevice;
import dev.nocs.events.EquipmentEventPublisher;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

import java.util.List;

import static org.mockito.Mockito.mock;

/**
 * Manual test to verify EAF driver loads and can discover devices.
 * Run with: ./gradlew test --tests EafDriverLoadTest
 * Requires: NOCS_EAF_SDK_PATH set (e.g. /tmp/indi-3rdparty/libasi/x64) and libudev installed.
 */
@EnabledIfEnvironmentVariable(named = "NOCS_EAF_SDK_PATH", matches = ".+")
class EafDriverLoadTest {

    private final EquipmentEventPublisher eventPublisher = mock(EquipmentEventPublisher.class);

    @Test
    void loadDriver_andListDevices() {
        String sdkPath = System.getenv("NOCS_EAF_SDK_PATH");
        System.out.println("Loading EAF driver with SDK path: " + sdkPath);

        EafDriver driver = new EafDriver(eventPublisher, sdkPath);
        driver.load();

        System.out.println("Loaded: " + driver.isLoaded());
        System.out.println("Driver status: " + driver.getDriverStatus());

        List<LogicalDevice> devices = driver.getLogicalDevices();
        System.out.println("Devices found: " + devices.size());
        devices.forEach(d -> System.out.println("  - " + d.displayName() + " (vid=" + d.vendorId() + " pid=" + d.productId() + " index=" + d.index() + ")"));

        if (!devices.isEmpty()) {
            driver.setDriverConfiguration(driver.getDriverConfiguration());
            driver.connect();
            System.out.println("Connected: " + driver.getDriverStatus().connectionState());
            System.out.println("Status: " + driver.getStatus());
            driver.disconnect();
        }

        driver.unload();
        System.out.println("Done.");
    }
}
