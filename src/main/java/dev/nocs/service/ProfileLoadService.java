package dev.nocs.service;

import dev.nocs.repository.ProfileRepository;
import org.springframework.stereotype.Service;

import java.util.Optional;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Manages profile loading and unloading. Only one profile can be loaded at a time.
 * Loading a profile loads all its drivers and connects equipment; unloading
 * disconnects and unloads them.
 */
@Service
public class ProfileLoadService {

    private final ProfileRepository profileRepository;
    private final DriverRegistry driverRegistry;
    private final FocuserService focuserService;
    private final MountService mountService;
    private final CameraService cameraService;
    private final FilterWheelService filterWheelService;

    private final AtomicReference<String> loadedProfileId = new AtomicReference<>();

    public ProfileLoadService(ProfileRepository profileRepository, DriverRegistry driverRegistry,
                             FocuserService focuserService, MountService mountService,
                             CameraService cameraService, FilterWheelService filterWheelService) {
        this.profileRepository = profileRepository;
        this.driverRegistry = driverRegistry;
        this.focuserService = focuserService;
        this.mountService = mountService;
        this.cameraService = cameraService;
        this.filterWheelService = filterWheelService;
    }

    /**
     * Load a profile. Unloads the current profile first if any. Then loads
     * all drivers referenced by the profile and connects equipment.
     */
    public void loadProfile(String profileId) {
        profileRepository.findById(profileId).ifPresent(profile -> {
            unloadProfile();
            profile.driverIds().forEach(driverRegistry::loadDriver);
            loadedProfileId.set(profileId);
            focuserService.connect();
            mountService.connect();
            cameraService.connect();
            filterWheelService.connect();
        });
    }

    /**
     * Unload the currently loaded profile. Unloads all drivers and clears
     * the loaded profile.
     */
    public void unloadProfile() {
        if (loadedProfileId.getAndSet(null) != null) {
            driverRegistry.unloadAll();
        }
    }

    /**
     * Unload a profile if it is currently loaded. Used when deleting a profile.
     */
    public void unloadIfLoaded(String profileId) {
        if (profileId.equals(loadedProfileId.get())) {
            unloadProfile();
        }
    }

    public Optional<String> getLoadedProfileId() {
        return Optional.ofNullable(loadedProfileId.get());
    }
}
