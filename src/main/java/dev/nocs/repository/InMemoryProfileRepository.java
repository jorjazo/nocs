package dev.nocs.repository;

import dev.nocs.domain.Profile;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

/**
 * In-memory profile repository for Phase 0.
 */
@Repository
public class InMemoryProfileRepository implements ProfileRepository {

    private final Map<String, Profile> store = new ConcurrentHashMap<>();

    @Override
    public Profile save(Profile profile) {
        store.put(profile.id(), profile);
        return profile;
    }

    @Override
    public Optional<Profile> findById(String id) {
        return Optional.ofNullable(store.get(id));
    }

    @Override
    public List<Profile> findAll() {
        return List.copyOf(store.values());
    }

    @Override
    public void deleteById(String id) {
        store.remove(id);
    }
}
