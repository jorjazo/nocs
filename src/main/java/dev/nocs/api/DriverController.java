package dev.nocs.api;

import dev.nocs.domain.Driver;
import dev.nocs.service.DriverRegistry;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * REST API for drivers (Phase 0).
 */
@RestController
@RequestMapping("/drivers")
public class DriverController {

    private final DriverRegistry driverRegistry;

    public DriverController(DriverRegistry driverRegistry) {
        this.driverRegistry = driverRegistry;
    }

    /**
     * List all available drivers.
     */
    @GetMapping
    public List<Driver> listDrivers() {
        return driverRegistry.listDrivers();
    }

    /**
     * Get a driver by id (canonical class name).
     */
    @GetMapping("/{driverId}")
    public ResponseEntity<Driver> getDriver(@PathVariable String driverId) {
        return driverRegistry.getDriver(driverId)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }
}
