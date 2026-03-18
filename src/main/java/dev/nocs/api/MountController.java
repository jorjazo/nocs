package dev.nocs.api;

import dev.nocs.domain.equipment.DriverStatus;
import dev.nocs.domain.equipment.mount.MountConfiguration;
import dev.nocs.domain.equipment.mount.MountDriverConfiguration;
import dev.nocs.domain.equipment.mount.MountStatus;
import dev.nocs.service.MountService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@Tag(name = "Mount", description = "Mount status, configuration, and actions")
@RestController
@RequestMapping("/mount")
public class MountController {

    private final MountService mountService;

    public MountController(MountService mountService) {
        this.mountService = mountService;
    }

    @Operation(summary = "Get mount status")
    @ApiResponse(responseCode = "200", description = "Mount status (RA, Dec, tracking, slewing, parked)")
    @ApiResponse(responseCode = "404", description = "No mount driver loaded")
    @GetMapping("/status")
    public ResponseEntity<MountStatus> getStatus() {
        return mountService.getStatus()
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @Operation(summary = "Get mount configuration")
    @ApiResponse(responseCode = "200", description = "Mount configuration")
    @ApiResponse(responseCode = "404", description = "No mount driver loaded")
    @GetMapping("/configuration")
    public ResponseEntity<MountConfiguration> getConfiguration() {
        return mountService.getConfiguration()
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @Operation(summary = "Update mount configuration")
    @ApiResponse(responseCode = "204", description = "Configuration updated")
    @ApiResponse(responseCode = "404", description = "No mount driver loaded")
    @PutMapping("/configuration")
    public ResponseEntity<Void> putConfiguration(@RequestBody MountConfiguration config) {
        if (mountService.getConfiguration().isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        mountService.setConfiguration(config);
        return ResponseEntity.noContent().build();
    }

    @Operation(summary = "Get mount driver status")
    @ApiResponse(responseCode = "200", description = "Driver connection status")
    @ApiResponse(responseCode = "404", description = "No mount driver loaded")
    @GetMapping("/driver/status")
    public ResponseEntity<DriverStatus> getDriverStatus() {
        return mountService.getDriverStatus()
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @Operation(summary = "Get mount driver configuration")
    @ApiResponse(responseCode = "200", description = "Driver configuration (host, port, serial)")
    @ApiResponse(responseCode = "404", description = "No mount driver loaded")
    @GetMapping("/driver/configuration")
    public ResponseEntity<MountDriverConfiguration> getDriverConfiguration() {
        return mountService.getDriverConfiguration()
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @Operation(summary = "Update mount driver configuration")
    @ApiResponse(responseCode = "204", description = "Driver configuration updated")
    @ApiResponse(responseCode = "404", description = "No mount driver loaded")
    @PutMapping("/driver/configuration")
    public ResponseEntity<Void> putDriverConfiguration(@RequestBody MountDriverConfiguration config) {
        if (mountService.getDriverConfiguration().isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        mountService.setDriverConfiguration(config);
        return ResponseEntity.noContent().build();
    }

    @Operation(summary = "Connect mount")
    @ApiResponse(responseCode = "204", description = "Connect requested")
    @ApiResponse(responseCode = "404", description = "No mount driver loaded")
    @PostMapping("/connect")
    public ResponseEntity<Void> connect() {
        if (mountService.getDriverStatus().isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        mountService.connect();
        return ResponseEntity.noContent().build();
    }

    @Operation(summary = "Disconnect mount")
    @ApiResponse(responseCode = "204", description = "Disconnect requested")
    @PostMapping("/disconnect")
    public ResponseEntity<Void> disconnect() {
        mountService.disconnect();
        return ResponseEntity.noContent().build();
    }

    @Operation(summary = "Slew to position")
    @ApiResponse(responseCode = "204", description = "Goto started")
    @ApiResponse(responseCode = "404", description = "No mount driver loaded")
    @PostMapping("/goto")
    public ResponseEntity<Void> gotoPosition(@RequestBody GotoRequest request) {
        if (mountService.getStatus().isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        mountService.gotoPosition(request.raHours(), request.decDegrees());
        return ResponseEntity.noContent().build();
    }

    @Operation(summary = "Park mount")
    @ApiResponse(responseCode = "204", description = "Park started")
    @ApiResponse(responseCode = "404", description = "No mount driver loaded")
    @PostMapping("/park")
    public ResponseEntity<Void> park() {
        if (mountService.getStatus().isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        mountService.park();
        return ResponseEntity.noContent().build();
    }

    @Operation(summary = "Sync to position")
    @ApiResponse(responseCode = "204", description = "Sync completed")
    @ApiResponse(responseCode = "404", description = "No mount driver loaded")
    @PostMapping("/sync")
    public ResponseEntity<Void> sync(@RequestBody SyncRequest request) {
        if (mountService.getStatus().isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        mountService.sync(request.raHours(), request.decDegrees());
        return ResponseEntity.noContent().build();
    }

    @Operation(summary = "Start tracking")
    @ApiResponse(responseCode = "204", description = "Tracking started")
    @PostMapping("/tracking/start")
    public ResponseEntity<Void> startTracking() {
        mountService.startTracking();
        return ResponseEntity.noContent().build();
    }

    @Operation(summary = "Stop tracking")
    @ApiResponse(responseCode = "204", description = "Tracking stopped")
    @PostMapping("/tracking/stop")
    public ResponseEntity<Void> stopTracking() {
        mountService.stopTracking();
        return ResponseEntity.noContent().build();
    }

    @io.swagger.v3.oas.annotations.media.Schema(description = "Goto request")
    public record GotoRequest(
            @io.swagger.v3.oas.annotations.media.Schema(requiredMode = io.swagger.v3.oas.annotations.media.Schema.RequiredMode.REQUIRED)
            double raHours,
            @io.swagger.v3.oas.annotations.media.Schema(requiredMode = io.swagger.v3.oas.annotations.media.Schema.RequiredMode.REQUIRED)
            double decDegrees) {}

    @io.swagger.v3.oas.annotations.media.Schema(description = "Sync request")
    public record SyncRequest(
            @io.swagger.v3.oas.annotations.media.Schema(requiredMode = io.swagger.v3.oas.annotations.media.Schema.RequiredMode.REQUIRED)
            double raHours,
            @io.swagger.v3.oas.annotations.media.Schema(requiredMode = io.swagger.v3.oas.annotations.media.Schema.RequiredMode.REQUIRED)
            double decDegrees) {}
}
