package dev.nocs.api;

import dev.nocs.domain.Driver;
import dev.nocs.service.DriverRegistry;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@Tag(name = "Drivers", description = "Equipment driver metadata and discovery")
@RestController
@RequestMapping("/drivers")
public class DriverController {

    private final DriverRegistry driverRegistry;

    public DriverController(DriverRegistry driverRegistry) {
        this.driverRegistry = driverRegistry;
    }

    @Operation(summary = "List drivers", description = "List all available equipment drivers")
    @ApiResponse(responseCode = "200", description = "List of driver metadata")
    @GetMapping
    public List<Driver> listDrivers() {
        return driverRegistry.listDrivers();
    }

    @Operation(summary = "Get driver", description = "Get a driver by id (canonical class name)")
    @ApiResponse(responseCode = "200", description = "Driver found")
    @ApiResponse(responseCode = "404", description = "Driver not found")
    @GetMapping("/{driverId}")
    public ResponseEntity<Driver> getDriver(@PathVariable String driverId) {
        return driverRegistry.getDriver(driverId)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }
}
