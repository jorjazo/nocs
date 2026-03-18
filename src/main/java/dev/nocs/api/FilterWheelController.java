package dev.nocs.api;

import dev.nocs.domain.equipment.DriverStatus;
import dev.nocs.domain.equipment.filterwheel.FilterWheelConfiguration;
import dev.nocs.domain.equipment.filterwheel.FilterWheelDriverConfiguration;
import dev.nocs.domain.equipment.filterwheel.FilterWheelStatus;
import dev.nocs.service.FilterWheelService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@Tag(name = "Filter Wheel", description = "Filter wheel status, configuration, and actions")
@RestController
@RequestMapping("/filterwheel")
public class FilterWheelController {

    private final FilterWheelService filterWheelService;

    public FilterWheelController(FilterWheelService filterWheelService) {
        this.filterWheelService = filterWheelService;
    }

    @Operation(summary = "Get filter wheel status")
    @ApiResponse(responseCode = "200", description = "Filter wheel status (current slot, moving)")
    @ApiResponse(responseCode = "404", description = "No filter wheel driver loaded")
    @GetMapping("/status")
    public ResponseEntity<FilterWheelStatus> getStatus() {
        return filterWheelService.getStatus()
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @Operation(summary = "Get filter wheel configuration")
    @ApiResponse(responseCode = "200", description = "Filter wheel configuration (filter names)")
    @ApiResponse(responseCode = "404", description = "No filter wheel driver loaded")
    @GetMapping("/configuration")
    public ResponseEntity<FilterWheelConfiguration> getConfiguration() {
        return filterWheelService.getConfiguration()
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @Operation(summary = "Update filter wheel configuration")
    @ApiResponse(responseCode = "204", description = "Configuration updated")
    @ApiResponse(responseCode = "404", description = "No filter wheel driver loaded")
    @PutMapping("/configuration")
    public ResponseEntity<Void> putConfiguration(@RequestBody FilterWheelConfiguration config) {
        if (filterWheelService.getConfiguration().isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        filterWheelService.setConfiguration(config);
        return ResponseEntity.noContent().build();
    }

    @Operation(summary = "Get filter wheel driver status")
    @ApiResponse(responseCode = "200", description = "Driver connection status")
    @ApiResponse(responseCode = "404", description = "No filter wheel driver loaded")
    @GetMapping("/driver/status")
    public ResponseEntity<DriverStatus> getDriverStatus() {
        return filterWheelService.getDriverStatus()
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @Operation(summary = "Get filter wheel driver configuration")
    @ApiResponse(responseCode = "200", description = "Driver configuration (serial port)")
    @ApiResponse(responseCode = "404", description = "No filter wheel driver loaded")
    @GetMapping("/driver/configuration")
    public ResponseEntity<FilterWheelDriverConfiguration> getDriverConfiguration() {
        return filterWheelService.getDriverConfiguration()
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @Operation(summary = "Update filter wheel driver configuration")
    @ApiResponse(responseCode = "204", description = "Driver configuration updated")
    @PutMapping("/driver/configuration")
    public ResponseEntity<Void> putDriverConfiguration(@RequestBody FilterWheelDriverConfiguration config) {
        filterWheelService.setDriverConfiguration(config);
        return ResponseEntity.noContent().build();
    }

    @Operation(summary = "Connect filter wheel")
    @ApiResponse(responseCode = "204", description = "Connect requested")
    @PostMapping("/connect")
    public ResponseEntity<Void> connect() {
        filterWheelService.connect();
        return ResponseEntity.noContent().build();
    }

    @Operation(summary = "Disconnect filter wheel")
    @ApiResponse(responseCode = "204", description = "Disconnect requested")
    @PostMapping("/disconnect")
    public ResponseEntity<Void> disconnect() {
        filterWheelService.disconnect();
        return ResponseEntity.noContent().build();
    }

    @Operation(summary = "Select filter slot")
    @ApiResponse(responseCode = "204", description = "Slot selection started")
    @ApiResponse(responseCode = "404", description = "No filter wheel driver loaded")
    @PostMapping("/select/{slot}")
    public ResponseEntity<Void> selectSlot(@PathVariable int slot) {
        if (filterWheelService.getStatus().isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        filterWheelService.selectSlot(slot);
        return ResponseEntity.noContent().build();
    }
}
