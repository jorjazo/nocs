package dev.nocs.api;

import dev.nocs.domain.DeviceReference;
import dev.nocs.domain.OpticalTrain;
import dev.nocs.service.OpticalTrainService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@Tag(name = "Optical Trains", description = "Optical train CRUD (first-class entities, shareable across profiles)")
@RestController
@RequestMapping("/optical-trains")
public class OpticalTrainController {

    private final OpticalTrainService opticalTrainService;

    public OpticalTrainController(OpticalTrainService opticalTrainService) {
        this.opticalTrainService = opticalTrainService;
    }

    @Operation(summary = "List optical trains")
    @ApiResponse(responseCode = "200", description = "List of all optical trains")
    @GetMapping
    public List<OpticalTrain> list() {
        return opticalTrainService.findAll();
    }

    @Operation(summary = "Get optical train by id")
    @ApiResponse(responseCode = "200", description = "Optical train found")
    @ApiResponse(responseCode = "404", description = "Optical train not found")
    @GetMapping("/{id}")
    public ResponseEntity<OpticalTrain> get(@PathVariable String id) {
        return opticalTrainService.findById(id)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @Operation(summary = "Create optical train")
    @ApiResponse(responseCode = "200", description = "Optical train created")
    @ApiResponse(responseCode = "400", description = "Validation failed")
    @PostMapping
    public OpticalTrain create(@RequestBody CreateOpticalTrainRequest request) {
        return opticalTrainService.create(
                request.name(),
                request.focalLengthMm(),
                request.apertureMm(),
                request.camera(),
                request.focuser(),
                request.filterWheel());
    }

    @Operation(summary = "Update optical train")
    @ApiResponse(responseCode = "200", description = "Optical train updated")
    @ApiResponse(responseCode = "404", description = "Optical train not found")
    @PutMapping("/{id}")
    public ResponseEntity<OpticalTrain> update(@PathVariable String id, @RequestBody UpdateOpticalTrainRequest request) {
        return opticalTrainService.update(
                id,
                request.name(),
                request.focalLengthMm(),
                request.apertureMm(),
                request.camera(),
                request.focuser(),
                request.filterWheel())
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @Operation(summary = "Delete optical train")
    @ApiResponse(responseCode = "204", description = "Optical train deleted")
    @ApiResponse(responseCode = "404", description = "Optical train not found")
    @DeleteMapping("/{id}")
    public ResponseEntity<Void> delete(@PathVariable String id) {
        if (opticalTrainService.findById(id).isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        opticalTrainService.deleteById(id);
        return ResponseEntity.noContent().build();
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, String>> handleValidation(IllegalArgumentException ex) {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .body(Map.of("error", ex.getMessage()));
    }

    @io.swagger.v3.oas.annotations.media.Schema(description = "Request to create an optical train")
    public record CreateOpticalTrainRequest(
            @io.swagger.v3.oas.annotations.media.Schema(requiredMode = io.swagger.v3.oas.annotations.media.Schema.RequiredMode.REQUIRED)
            String name,
            @io.swagger.v3.oas.annotations.media.Schema(requiredMode = io.swagger.v3.oas.annotations.media.Schema.RequiredMode.REQUIRED)
            double focalLengthMm,
            Double apertureMm,
            DeviceReference camera,
            DeviceReference focuser,
            DeviceReference filterWheel
    ) {}

    @io.swagger.v3.oas.annotations.media.Schema(description = "Request to update an optical train")
    public record UpdateOpticalTrainRequest(
            String name,
            Double focalLengthMm,
            Double apertureMm,
            DeviceReference camera,
            DeviceReference focuser,
            DeviceReference filterWheel
    ) {}
}
