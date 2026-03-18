package dev.nocs.service;

import dev.nocs.repository.ProfileRepository;
import org.springframework.stereotype.Service;

import java.util.Optional;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Manages profile loading and unloading. Only one profile can be loaded at a time.
 * Loading a profile loads all its drivers; unloading unloads them.
 */
@Service
public class ProfileLoadService {

    private final ProfileRepository profileRepository;
    private final DriverRegistry driverRegistry;

    private final AtomicReference<String> loadedProfileId = new AtomicReference<>();

    public ProfileLoadService(ProfileRepository profileRepository, DriverRegistry driverRegistry) {
        this.profileRepository = profileRepository;
        this.driverRegistry = driverRegistry;
    }

    /**
     * Load a profile. Unloads the current profile first if any. Then loads
     * all drivers referenced by the profile.
     */
    public void loadProfile(String profileId) {
        profileRepository.findById(profileId).ifPresent(profile -> {
            unloadProfile();
            profile.driverIds().forEach(driverRegistry::loadDriver);
            loadedProfileId.set(profileId);
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
