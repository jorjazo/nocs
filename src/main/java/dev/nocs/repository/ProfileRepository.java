package dev.nocs.repository;

import dev.nocs.domain.Profile;

import java.util.List;
import java.util.Optional;

/**
 * Repository for profiles.
 */
public interface ProfileRepository {

    Profile save(Profile profile);

    Optional<Profile> findById(String id);

    List<Profile> findAll();

    void deleteById(String id);
}
