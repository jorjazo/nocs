package dev.nocs.service;

import dev.nocs.domain.Profile;
import dev.nocs.repository.InMemoryProfileRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;

class ProfileServiceTest {

    private InMemoryProfileRepository repository;
    private ProfileLoadService profileLoadService;
    private ProfileService profileService;
    private DriverRegistry driverRegistry;

    @BeforeEach
    void setUp() {
        repository = new InMemoryProfileRepository();
        driverRegistry = new DriverRegistry(List.of());
        profileLoadService = new ProfileLoadService(repository, driverRegistry);
        profileService = new ProfileService(repository, profileLoadService);
    }

    @Test
    void create_and_findById() {
        Profile created = profileService.create("Test Profile", List.of("driver.one"));

        assertThat(created.id()).isNotNull();
        assertThat(created.name()).isEqualTo("Test Profile");
        assertThat(created.driverIds()).containsExactly("driver.one");

        Optional<Profile> found = profileService.findById(created.id());
        assertThat(found).isPresent();
        assertThat(found.get()).isEqualTo(created);
    }

    @Test
    void update() {
        Profile created = profileService.create("Original", List.of("driver.one"));
        profileService.update(created.id(), "Updated", List.of("driver.one", "driver.two"));

        Optional<Profile> updated = profileService.findById(created.id());
        assertThat(updated).isPresent();
        assertThat(updated.get().name()).isEqualTo("Updated");
        assertThat(updated.get().driverIds()).containsExactly("driver.one", "driver.two");
    }

    @Test
    void deleteById() {
        Profile created = profileService.create("To Delete", List.of());
        profileService.deleteById(created.id());

        assertThat(profileService.findById(created.id())).isEmpty();
    }

    @Test
    void getLoadedProfileId_emptyInitially() {
        assertThat(profileService.getLoadedProfileId()).isEmpty();
    }
}
