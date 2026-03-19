package dev.nocs.driver.efw;

import dev.nocs.domain.LogicalDevice;
import dev.nocs.events.EquipmentEventPublisher;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

import java.util.List;

import static org.mockito.Mockito.mock;

/**
 * Manual test to verify EFW driver loads and can discover devices.
 * Run with: ./gradlew test --tests EfwDriverLoadTest
 * Requires: NOCS_EFW_SDK_PATH set (e.g. native/linux-x64) and libudev installed.
 */
@EnabledIfEnvironmentVariable(named = "NOCS_EFW_SDK_PATH", matches = ".+")
class EfwDriverLoadTest {

    private final EquipmentEventPublisher eventPublisher = mock(EquipmentEventPublisher.class);

    @Test
    void loadDriver_andListDevices() {
        String sdkPath = System.getenv("NOCS_EFW_SDK_PATH");
        System.out.println("Loading EFW driver with SDK path: " + sdkPath);

        EfwDriver driver = new EfwDriver(eventPublisher, sdkPath);
        driver.load();

        System.out.println("Loaded: " + driver.isLoaded());
        System.out.println("Driver status: " + driver.getDriverStatus());

        List<LogicalDevice> devices = driver.getLogicalDevices();
        System.out.println("Devices found: " + devices.size());
        devices.forEach(d -> System.out.println("  - " + d.displayName()
                + " (vid=" + d.vendorId() + " pid=" + d.productId() + " index=" + d.index() + ")"));

        if (!devices.isEmpty()) {
            driver.setDriverConfiguration(driver.getDriverConfiguration());
            driver.connect();
            System.out.println("Connected: " + driver.getDriverStatus().connectionState());
            System.out.println("Status: " + driver.getStatus());
            System.out.println("Configuration: " + driver.getConfiguration());
            driver.disconnect();
        }

        driver.unload();
        System.out.println("Done.");
    }
}
