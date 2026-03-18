package dev.nocs.service;

import dev.nocs.domain.DeviceReference;
import dev.nocs.domain.OpticalTrain;
import dev.nocs.domain.Profile;
import dev.nocs.repository.ProfileRepository;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;

/**
 * CRUD and load/unload operations for profiles.
 */
@Service
public class ProfileService {

    private final ProfileRepository profileRepository;
    private final ProfileLoadService profileLoadService;
    private final OpticalTrainService opticalTrainService;

    public ProfileService(ProfileRepository profileRepository, ProfileLoadService profileLoadService,
                         OpticalTrainService opticalTrainService) {
        this.profileRepository = profileRepository;
        this.profileLoadService = profileLoadService;
        this.opticalTrainService = opticalTrainService;
    }

    public List<Profile> findAll() {
        return profileRepository.findAll();
    }

    public Optional<Profile> findById(String id) {
        return profileRepository.findById(id);
    }

    public Profile create(String name, List<String> driverIds,
                         List<String> imagingTrainIds, String guidingTrainId,
                         List<DeviceReference> mountPriority) {
        validateGuidingTrainNotImaging(imagingTrainIds, guidingTrainId);
        List<OpticalTrain> trains = resolveTrains(imagingTrainIds, guidingTrainId);
        validateCameraUniqueness(trains);
        Profile profile = new Profile(
                UUID.randomUUID().toString(),
                name,
                driverIds != null ? driverIds : List.of(),
                imagingTrainIds != null ? imagingTrainIds : List.of(),
                guidingTrainId,
                mountPriority != null ? mountPriority : List.of());
        return profileRepository.save(profile);
    }

    public Optional<Profile> update(String id, String name, List<String> driverIds,
                                   List<String> imagingTrainIds, String guidingTrainId,
                                   List<DeviceReference> mountPriority) {
        return profileRepository.findById(id)
                .map(p -> {
                    List<String> ids = imagingTrainIds != null ? imagingTrainIds : p.imagingTrainIds();
                    String guideId = guidingTrainId != null ? guidingTrainId : p.guidingTrainId();
                    validateGuidingTrainNotImaging(ids, guideId);
                    List<OpticalTrain> trains = resolveTrains(ids, guideId);
                    validateCameraUniqueness(trains);
                    return new Profile(
                            p.id(),
                            name != null ? name : p.name(),
                            driverIds != null ? driverIds : p.driverIds(),
                            ids,
                            guideId,
                            mountPriority != null ? mountPriority : p.mountPriority());
                })
                .map(profileRepository::save);
    }

    private List<OpticalTrain> resolveTrains(List<String> imagingTrainIds, String guidingTrainId) {
        List<OpticalTrain> trains = new ArrayList<>();
        if (imagingTrainIds != null) {
            for (String trainId : imagingTrainIds) {
                opticalTrainService.findById(trainId).ifPresent(trains::add);
            }
        }
        if (guidingTrainId != null) {
            opticalTrainService.findById(guidingTrainId).ifPresent(trains::add);
        }
        return trains;
    }

    /**
     * Guiding train must not be any of the imaging trains.
     */
    private void validateGuidingTrainNotImaging(List<String> imagingTrainIds, String guidingTrainId) {
        if (guidingTrainId != null && imagingTrainIds != null && imagingTrainIds.contains(guidingTrainId)) {
            throw new IllegalArgumentException("Guiding train cannot be one of the imaging trains");
        }
    }

    /**
     * Each camera can only be used by one optical train per profile.
     */
    private void validateCameraUniqueness(List<OpticalTrain> trains) {
        Set<String> cameraKeys = new HashSet<>();
        for (OpticalTrain t : trains) {
            t.cameraOpt().map(DeviceReference::key).ifPresent(key -> {
                if (!cameraKeys.add(key)) {
                    throw new IllegalArgumentException("Camera " + key + " is used by more than one optical train");
                }
            });
        }
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
