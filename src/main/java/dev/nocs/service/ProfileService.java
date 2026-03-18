package dev.nocs.service;

import dev.nocs.domain.Profile;
import dev.nocs.repository.ProfileRepository;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

/**
 * CRUD and load/unload operations for profiles.
 */
@Service
public class ProfileService {

    private final ProfileRepository profileRepository;
    private final ProfileLoadService profileLoadService;

    public ProfileService(ProfileRepository profileRepository, ProfileLoadService profileLoadService) {
        this.profileRepository = profileRepository;
        this.profileLoadService = profileLoadService;
    }

    public List<Profile> findAll() {
        return profileRepository.findAll();
    }

    public Optional<Profile> findById(String id) {
        return profileRepository.findById(id);
    }

    public Profile create(String name, List<String> driverIds) {
        Profile profile = new Profile(UUID.randomUUID().toString(), name, driverIds != null ? driverIds : List.of());
        return profileRepository.save(profile);
    }

    public Optional<Profile> update(String id, String name, List<String> driverIds) {
        return profileRepository.findById(id)
                .map(p -> new Profile(p.id(), name != null ? name : p.name(), driverIds != null ? driverIds : p.driverIds()))
                .map(profileRepository::save);
    }

    public void deleteById(String id) {
        profileLoadService.unloadIfLoaded(id);
        profileRepository.deleteById(id);
    }

    public void loadProfile(String id) {
        profileLoadService.loadProfile(id);
    }

    public void unloadProfile() {
        profileLoadService.unloadProfile();
    }

    public Optional<String> getLoadedProfileId() {
        return profileLoadService.getLoadedProfileId();
    }
}
