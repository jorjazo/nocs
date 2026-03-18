package dev.nocs.api;

import dev.nocs.domain.equipment.DriverStatus;
import dev.nocs.domain.equipment.camera.CameraConfiguration;
import dev.nocs.domain.equipment.camera.CameraDriverConfiguration;
import dev.nocs.domain.equipment.camera.CameraStatus;
import dev.nocs.service.CameraService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@Tag(name = "Camera", description = "Camera status, configuration, and actions")
@RestController
@RequestMapping("/camera")
public class CameraController {

    private final CameraService cameraService;

    public CameraController(CameraService cameraService) {
        this.cameraService = cameraService;
    }

    @Operation(summary = "Get camera status")
    @ApiResponse(responseCode = "200", description = "Camera status (exposing, temperature, current frame)")
    @ApiResponse(responseCode = "404", description = "No camera driver loaded")
    @GetMapping("/status")
    public ResponseEntity<CameraStatus> getStatus() {
        return cameraService.getStatus()
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @Operation(summary = "Get camera configuration")
    @ApiResponse(responseCode = "200", description = "Camera configuration")
    @ApiResponse(responseCode = "404", description = "No camera driver loaded")
    @GetMapping("/configuration")
    public ResponseEntity<CameraConfiguration> getConfiguration() {
        return cameraService.getConfiguration()
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @Operation(summary = "Update camera configuration")
    @ApiResponse(responseCode = "204", description = "Configuration updated")
    @ApiResponse(responseCode = "404", description = "No camera driver loaded")
    @PutMapping("/configuration")
    public ResponseEntity<Void> putConfiguration(@RequestBody CameraConfiguration config) {
        if (cameraService.getConfiguration().isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        cameraService.setConfiguration(config);
        return ResponseEntity.noContent().build();
    }

    @Operation(summary = "Get camera driver status")
    @ApiResponse(responseCode = "200", description = "Driver connection status")
    @ApiResponse(responseCode = "404", description = "No camera driver loaded")
    @GetMapping("/driver/status")
    public ResponseEntity<DriverStatus> getDriverStatus() {
        return cameraService.getDriverStatus()
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @Operation(summary = "Get camera driver configuration")
    @ApiResponse(responseCode = "200", description = "Driver configuration")
    @ApiResponse(responseCode = "404", description = "No camera driver loaded")
    @GetMapping("/driver/configuration")
    public ResponseEntity<CameraDriverConfiguration> getDriverConfiguration() {
        return cameraService.getDriverConfiguration()
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @Operation(summary = "Update camera driver configuration")
    @ApiResponse(responseCode = "204", description = "Driver configuration updated")
    @PutMapping("/driver/configuration")
    public ResponseEntity<Void> putDriverConfiguration(@RequestBody CameraDriverConfiguration config) {
        cameraService.setDriverConfiguration(config);
        return ResponseEntity.noContent().build();
    }

    @Operation(summary = "Connect camera")
    @ApiResponse(responseCode = "204", description = "Connect requested")
    @PostMapping("/connect")
    public ResponseEntity<Void> connect() {
        cameraService.connect();
        return ResponseEntity.noContent().build();
    }

    @Operation(summary = "Disconnect camera")
    @ApiResponse(responseCode = "204", description = "Disconnect requested")
    @PostMapping("/disconnect")
    public ResponseEntity<Void> disconnect() {
        cameraService.disconnect();
        return ResponseEntity.noContent().build();
    }

    @Operation(summary = "Start exposure")
    @ApiResponse(responseCode = "200", description = "Exposure started, returns frame id")
    @ApiResponse(responseCode = "404", description = "No camera driver loaded")
    @PostMapping("/expose")
    public ResponseEntity<ExposeResponse> expose(@RequestBody ExposeRequest request) {
        return cameraService.startExposure(request.durationSeconds())
                .map(frameId -> ResponseEntity.ok(new ExposeResponse(frameId)))
                .orElse(ResponseEntity.notFound().build());
    }

    @Operation(summary = "Get image")
    @ApiResponse(responseCode = "200", description = "Image data (placeholder for simulator)")
    @ApiResponse(responseCode = "404", description = "Frame not found or no camera driver")
    @GetMapping("/image/{frameId}")
    public ResponseEntity<byte[]> getImage(@PathVariable String frameId) {
        return cameraService.getImage(frameId)
                .map(bytes -> ResponseEntity.ok()
                        .contentType(MediaType.APPLICATION_OCTET_STREAM)
                        .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + frameId + ".bin\"")
                        .body(bytes))
                .orElse(ResponseEntity.notFound().build());
    }

    @io.swagger.v3.oas.annotations.media.Schema(description = "Expose request")
    public record ExposeRequest(
            @io.swagger.v3.oas.annotations.media.Schema(requiredMode = io.swagger.v3.oas.annotations.media.Schema.RequiredMode.REQUIRED)
            double durationSeconds) {}

    @io.swagger.v3.oas.annotations.media.Schema(description = "Expose response")
    public record ExposeResponse(String frameId) {}
}
