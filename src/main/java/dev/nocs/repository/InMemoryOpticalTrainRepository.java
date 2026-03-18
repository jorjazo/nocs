package dev.nocs.repository;

import dev.nocs.domain.OpticalTrain;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

/**
 * In-memory optical train repository.
 */
@Repository
public class InMemoryOpticalTrainRepository implements OpticalTrainRepository {

    private final Map<String, OpticalTrain> store = new ConcurrentHashMap<>();

    @Override
    public OpticalTrain save(OpticalTrain opticalTrain) {
        store.put(opticalTrain.id(), opticalTrain);
        return opticalTrain;
    }

    @Override
    public Optional<OpticalTrain> findById(String id) {
        return Optional.ofNullable(store.get(id));
    }

    @Override
    public List<OpticalTrain> findAll() {
        return List.copyOf(store.values());
    }

    @Override
    public void deleteById(String id) {
        store.remove(id);
    }
}
