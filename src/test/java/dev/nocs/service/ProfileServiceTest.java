package dev.nocs.service;

import dev.nocs.domain.OpticalTrain;
import dev.nocs.domain.Profile;
import dev.nocs.repository.InMemoryOpticalTrainRepository;
import dev.nocs.repository.InMemoryProfileRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;

class ProfileServiceTest {

    private InMemoryProfileRepository repository;
    private InMemoryOpticalTrainRepository opticalTrainRepository;
    private ProfileLoadService profileLoadService;
    private ProfileService profileService;
    private DriverRegistry driverRegistry;

    @BeforeEach
    void setUp() {
        repository = new InMemoryProfileRepository();
        opticalTrainRepository = new InMemoryOpticalTrainRepository();
        driverRegistry = new DriverRegistry(List.of());
        profileLoadService = new ProfileLoadService(repository, driverRegistry);
        OpticalTrainService opticalTrainService = new OpticalTrainService(opticalTrainRepository);
        profileService = new ProfileService(repository, profileLoadService, opticalTrainService);
    }

    @Test
    void create_and_findById() {
        Profile created = profileService.create("Test Profile", List.of("driver.one"), List.of(), null, List.of());

        assertThat(created.id()).isNotNull();
        assertThat(created.name()).isEqualTo("Test Profile");
        assertThat(created.driverIds()).containsExactly("driver.one");

        Optional<Profile> found = profileService.findById(created.id());
        assertThat(found).isPresent();
        assertThat(found.get()).isEqualTo(created);
    }

    @Test
    void update() {
        Profile created = profileService.create("Original", List.of("driver.one"), List.of(), null, List.of());
        profileService.update(created.id(), "Updated", List.of("driver.one", "driver.two"), null, null, null);

        Optional<Profile> updated = profileService.findById(created.id());
        assertThat(updated).isPresent();
        assertThat(updated.get().name()).isEqualTo("Updated");
        assertThat(updated.get().driverIds()).containsExactly("driver.one", "driver.two");
    }

    @Test
    void deleteById() {
        Profile created = profileService.create("To Delete", List.of(), List.of(), null, List.of());
        profileService.deleteById(created.id());

        assertThat(profileService.findById(created.id())).isEmpty();
    }

    @Test
    void getLoadedProfileId_emptyInitially() {
        assertThat(profileService.getLoadedProfileId()).isEmpty();
    }

    @Test
    void create_rejectsDuplicateCamera() {
        var ref = new dev.nocs.domain.DeviceReference(
                dev.nocs.domain.EquipmentType.CAMERA, "03c3", "120e", 0, "ASI Camera");
        OpticalTrain train1 = opticalTrainRepository.save(
                new OpticalTrain("t1", "Train 1", 600, null, ref, null, null));
        OpticalTrain train2 = opticalTrainRepository.save(
                new OpticalTrain("t2", "Train 2", 400, null, ref, null, null));

        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () ->
                profileService.create("Test", List.of(), List.of(train1.id(), train2.id()), null, List.of()));
    }
}
