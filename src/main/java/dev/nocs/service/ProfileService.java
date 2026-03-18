package dev.nocs.service;

import dev.nocs.domain.DeviceReference;
import dev.nocs.domain.OpticalTrain;
import dev.nocs.domain.Profile;
import dev.nocs.repository.ProfileRepository;
import org.springframework.stereotype.Service;

import java.util.HashSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Stream;

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

    public Profile create(String name, List<String> driverIds,
                         List<OpticalTrain> imagingTrains, OpticalTrain guidingTrain,
                         List<DeviceReference> mountPriority) {
        validateCameraUniqueness(imagingTrains, guidingTrain);
        Profile profile = new Profile(
                UUID.randomUUID().toString(),
                name,
                driverIds != null ? driverIds : List.of(),
                imagingTrains != null ? imagingTrains : List.of(),
                guidingTrain,
                mountPriority != null ? mountPriority : List.of());
        return profileRepository.save(profile);
    }

    public Optional<Profile> update(String id, String name, List<String> driverIds,
                                   List<OpticalTrain> imagingTrains, OpticalTrain guidingTrain,
                                   List<DeviceReference> mountPriority) {
        return profileRepository.findById(id)
                .map(p -> {
                    validateCameraUniqueness(
                            imagingTrains != null ? imagingTrains : p.imagingTrains(),
                            guidingTrain != null ? guidingTrain : p.guidingTrainOpt().orElse(null));
                    return new Profile(
                            p.id(),
                            name != null ? name : p.name(),
                            driverIds != null ? driverIds : p.driverIds(),
                            imagingTrains != null ? imagingTrains : p.imagingTrains(),
                            guidingTrain != null ? guidingTrain : p.guidingTrain(),
                            mountPriority != null ? mountPriority : p.mountPriority());
                })
                .map(profileRepository::save);
    }

    /**
     * Each camera can only be used by one optical train per profile.
     */
    private void validateCameraUniqueness(List<OpticalTrain> imagingTrains, OpticalTrain guidingTrain) {
        Set<String> cameraKeys = new HashSet<>();
        Stream.concat(
                        imagingTrains.stream(),
                        guidingTrain != null ? Stream.of(guidingTrain) : Stream.empty())
                .flatMap(t -> t.cameraOpt().stream())
                .map(DeviceReference::key)
                .forEach(key -> {
                    if (!cameraKeys.add(key)) {
                        throw new IllegalArgumentException("Camera " + key + " is used by more than one optical train");
                    }
                });
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
