package dev.nocs.api;

import dev.nocs.domain.equipment.DriverStatus;
import dev.nocs.domain.equipment.focuser.FocuserConfiguration;
import dev.nocs.domain.equipment.focuser.FocuserDriverConfiguration;
import dev.nocs.domain.equipment.focuser.FocuserStatus;
import dev.nocs.service.FocuserService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@Tag(name = "Focuser", description = "Focuser status, configuration, and actions")
@RestController
@RequestMapping("/focuser")
public class FocuserController {

    private final FocuserService focuserService;

    public FocuserController(FocuserService focuserService) {
        this.focuserService = focuserService;
    }

    @Operation(summary = "Get focuser status")
    @ApiResponse(responseCode = "200", description = "Focuser status (position, moving, temperature)")
    @ApiResponse(responseCode = "404", description = "No focuser driver loaded")
    @GetMapping("/status")
    public ResponseEntity<FocuserStatus> getStatus() {
        return focuserService.getStatus()
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @Operation(summary = "Get focuser configuration")
    @ApiResponse(responseCode = "200", description = "Focuser configuration")
    @ApiResponse(responseCode = "404", description = "No focuser driver loaded")
    @GetMapping("/configuration")
    public ResponseEntity<FocuserConfiguration> getConfiguration() {
        return focuserService.getConfiguration()
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @Operation(summary = "Update focuser configuration")
    @ApiResponse(responseCode = "204", description = "Configuration updated")
    @ApiResponse(responseCode = "404", description = "No focuser driver loaded")
    @PutMapping("/configuration")
    public ResponseEntity<Void> putConfiguration(@RequestBody FocuserConfiguration config) {
        if (focuserService.getConfiguration().isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        focuserService.setConfiguration(config);
        return ResponseEntity.noContent().build();
    }

    @Operation(summary = "Get focuser driver status")
    @ApiResponse(responseCode = "200", description = "Driver connection status")
    @ApiResponse(responseCode = "404", description = "No focuser driver loaded")
    @GetMapping("/driver/status")
    public ResponseEntity<DriverStatus> getDriverStatus() {
        return focuserService.getDriverStatus()
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @Operation(summary = "Get focuser driver configuration")
    @ApiResponse(responseCode = "200", description = "Driver configuration (serial port)")
    @ApiResponse(responseCode = "404", description = "No focuser driver loaded")
    @GetMapping("/driver/configuration")
    public ResponseEntity<FocuserDriverConfiguration> getDriverConfiguration() {
        return focuserService.getDriverConfiguration()
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @Operation(summary = "Update focuser driver configuration")
    @ApiResponse(responseCode = "204", description = "Driver configuration updated")
    @PutMapping("/driver/configuration")
    public ResponseEntity<Void> putDriverConfiguration(@RequestBody FocuserDriverConfiguration config) {
        focuserService.setDriverConfiguration(config);
        return ResponseEntity.noContent().build();
    }

    @Operation(summary = "Connect focuser")
    @ApiResponse(responseCode = "204", description = "Connect requested")
    @PostMapping("/connect")
    public ResponseEntity<Void> connect() {
        focuserService.connect();
        return ResponseEntity.noContent().build();
    }

    @Operation(summary = "Disconnect focuser")
    @ApiResponse(responseCode = "204", description = "Disconnect requested")
    @PostMapping("/disconnect")
    public ResponseEntity<Void> disconnect() {
        focuserService.disconnect();
        return ResponseEntity.noContent().build();
    }

    @Operation(summary = "Move focuser relative")
    @ApiResponse(responseCode = "204", description = "Move started")
    @ApiResponse(responseCode = "404", description = "No focuser driver loaded")
    @PostMapping("/move")
    public ResponseEntity<Void> moveRelative(@RequestBody MoveRequest request) {
        if (focuserService.getStatus().isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        focuserService.moveRelative(request.steps());
        return ResponseEntity.noContent().build();
    }

    @Operation(summary = "Move focuser to absolute position")
    @ApiResponse(responseCode = "204", description = "Move started")
    @ApiResponse(responseCode = "404", description = "No focuser driver loaded")
    @PostMapping("/absolute")
    public ResponseEntity<Void> moveAbsolute(@RequestBody AbsoluteRequest request) {
        if (focuserService.getStatus().isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        focuserService.moveAbsolute(request.position());
        return ResponseEntity.noContent().build();
    }

    @io.swagger.v3.oas.annotations.media.Schema(description = "Relative move request")
    public record MoveRequest(
            @io.swagger.v3.oas.annotations.media.Schema(requiredMode = io.swagger.v3.oas.annotations.media.Schema.RequiredMode.REQUIRED)
            int steps) {}

    @io.swagger.v3.oas.annotations.media.Schema(description = "Absolute move request")
    public record AbsoluteRequest(
            @io.swagger.v3.oas.annotations.media.Schema(requiredMode = io.swagger.v3.oas.annotations.media.Schema.RequiredMode.REQUIRED)
            int position) {}
}
