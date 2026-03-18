package dev.nocs.api;

import dev.nocs.domain.DeviceReference;
import dev.nocs.domain.OpticalTrain;
import dev.nocs.domain.Profile;
import dev.nocs.service.OpticalTrainService;
import dev.nocs.service.ProfileService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

@Tag(name = "Profiles", description = "Profile CRUD and load/unload")
@RestController
@RequestMapping("/profiles")
public class ProfileController {

    private final ProfileService profileService;
    private final OpticalTrainService opticalTrainService;

    public ProfileController(ProfileService profileService, OpticalTrainService opticalTrainService) {
        this.profileService = profileService;
        this.opticalTrainService = opticalTrainService;
    }

    @Operation(summary = "List profiles", description = "List all profiles with loaded status and resolved optical trains")
    @ApiResponse(responseCode = "200", description = "List of profiles, each with loaded flag")
    @GetMapping
    public List<ProfileListItem> listProfiles() {
        String loadedId = profileService.getLoadedProfileId().orElse(null);
        return profileService.findAll().stream()
                .map(p -> toListItem(p, p.id().equals(loadedId)))
                .toList();
    }

    @io.swagger.v3.oas.annotations.media.Schema(description = "Profile with loaded status and resolved optical trains")
    public record ProfileListItem(
            String id,
            String name,
            List<String> driverIds,
            List<String> imagingTrainIds,
            String guidingTrainId,
            List<OpticalTrain> imagingTrains,
            OpticalTrain guidingTrain,
            List<DeviceReference> mountPriority,
            boolean loaded
    ) {}

    @Operation(summary = "Get profile by id")
    @ApiResponse(responseCode = "200", description = "Profile found")
    @ApiResponse(responseCode = "404", description = "Profile not found")
    @GetMapping("/{id}")
    public ResponseEntity<ProfileResponse> getProfile(@PathVariable String id) {
        return profileService.findById(id)
                .map(p -> ResponseEntity.ok(toResponse(p)))
                .orElse(ResponseEntity.notFound().build());
    }

    @io.swagger.v3.oas.annotations.media.Schema(description = "Profile with resolved optical trains")
    public record ProfileResponse(
            String id,
            String name,
            List<String> driverIds,
            List<String> imagingTrainIds,
            String guidingTrainId,
            List<OpticalTrain> imagingTrains,
            OpticalTrain guidingTrain,
            List<DeviceReference> mountPriority
    ) {}

    @Operation(summary = "Create profile")
    @ApiResponse(responseCode = "200", description = "Profile created")
    @ApiResponse(responseCode = "400", description = "Validation failed (e.g. duplicate camera)")
    @PostMapping
    public ProfileResponse createProfile(@RequestBody CreateProfileRequest request) {
        Profile profile = profileService.create(
                request.name(),
                request.driverIds(),
                request.imagingTrainIds(),
                request.guidingTrainId(),
                request.mountPriority());
        return toResponse(profile);
    }

    @Operation(summary = "Update profile")
    @ApiResponse(responseCode = "200", description = "Profile updated")
    @ApiResponse(responseCode = "400", description = "Validation failed (e.g. duplicate camera)")
    @ApiResponse(responseCode = "404", description = "Profile not found")
    @PutMapping("/{id}")
    public ResponseEntity<ProfileResponse> updateProfile(@PathVariable String id, @RequestBody UpdateProfileRequest request) {
        return profileService.update(
                id,
                request.name(),
                request.driverIds(),
                request.imagingTrainIds(),
                request.guidingTrainId(),
                request.mountPriority())
                .map(p -> ResponseEntity.ok(toResponse(p)))
                .orElse(ResponseEntity.notFound().build());
    }

    @Operation(summary = "Delete profile")
    @ApiResponse(responseCode = "204", description = "Profile deleted")
    @ApiResponse(responseCode = "404", description = "Profile not found")
    @DeleteMapping("/{id}")
    public ResponseEntity<Void> deleteProfile(@PathVariable String id) {
        if (profileService.findById(id).isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        profileService.deleteById(id);
        return ResponseEntity.noContent().build();
    }

    @Operation(summary = "Load profile", description = "Load a profile. Unloads current profile first. Loads all drivers in the profile.")
    @ApiResponse(responseCode = "204", description = "Profile loaded")
    @ApiResponse(responseCode = "404", description = "Profile not found")
    @PostMapping("/{id}/load")
    public ResponseEntity<Void> loadProfile(@PathVariable String id) {
        if (profileService.findById(id).isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        profileService.loadProfile(id);
        return ResponseEntity.noContent().build();
    }

    @Operation(summary = "Unload profile", description = "Unload the currently loaded profile. Unloads all its drivers.")
    @ApiResponse(responseCode = "204", description = "Profile unloaded")
    @PostMapping("/unload")
    public ResponseEntity<Void> unloadProfile() {
        profileService.unloadProfile();
        return ResponseEntity.noContent().build();
    }

    private ProfileListItem toListItem(Profile p, boolean loaded) {
        List<OpticalTrain> imaging = resolveOpticalTrains(p.imagingTrainIds());
        OpticalTrain guiding = p.guidingTrainIdOpt()
                .flatMap(opticalTrainService::findById)
                .orElse(null);
        return new ProfileListItem(
                p.id(), p.name(), p.driverIds(),
                p.imagingTrainIds(), p.guidingTrainId(),
                imaging, guiding, p.mountPriority(),
                loaded);
    }

    private ProfileResponse toResponse(Profile p) {
        List<OpticalTrain> imaging = resolveOpticalTrains(p.imagingTrainIds());
        OpticalTrain guiding = p.guidingTrainIdOpt()
                .flatMap(opticalTrainService::findById)
                .orElse(null);
        return new ProfileResponse(
                p.id(), p.name(), p.driverIds(),
                p.imagingTrainIds(), p.guidingTrainId(),
                imaging, guiding, p.mountPriority());
    }

    private List<OpticalTrain> resolveOpticalTrains(List<String> ids) {
        List<OpticalTrain> result = new ArrayList<>();
        if (ids != null) {
            for (String id : ids) {
                opticalTrainService.findById(id).ifPresent(result::add);
            }
        }
        return result;
    }

    @io.swagger.v3.oas.annotations.media.Schema(description = "Request to create a profile")
    public record CreateProfileRequest(
            @io.swagger.v3.oas.annotations.media.Schema(requiredMode = io.swagger.v3.oas.annotations.media.Schema.RequiredMode.REQUIRED)
            String name,
            @io.swagger.v3.oas.annotations.media.Schema(description = "Driver class names to load when profile is loaded")
            List<String> driverIds,
            @io.swagger.v3.oas.annotations.media.Schema(description = "Imaging optical train IDs (0 or more)")
            List<String> imagingTrainIds,
            @io.swagger.v3.oas.annotations.media.Schema(description = "Guiding optical train ID (0 or 1)")
            String guidingTrainId,
            @io.swagger.v3.oas.annotations.media.Schema(description = "Mount priority list: highest priority first when multiple mounts available")
            List<DeviceReference> mountPriority
    ) {
        public CreateProfileRequest {
            if (driverIds == null) driverIds = List.of();
            if (imagingTrainIds == null) imagingTrainIds = List.of();
            if (mountPriority == null) mountPriority = List.of();
        }
    }

    @io.swagger.v3.oas.annotations.media.Schema(description = "Request to update a profile")
    public record UpdateProfileRequest(
            String name,
            List<String> driverIds,
            List<String> imagingTrainIds,
            String guidingTrainId,
            List<DeviceReference> mountPriority
    ) {}

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, String>> handleValidation(IllegalArgumentException ex) {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .body(Map.of("error", ex.getMessage()));
    }
}
