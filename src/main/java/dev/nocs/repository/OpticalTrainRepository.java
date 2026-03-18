package dev.nocs.repository;

import dev.nocs.domain.OpticalTrain;

import java.util.List;
import java.util.Optional;

/**
 * Repository for optical trains.
 */
public interface OpticalTrainRepository {

    OpticalTrain save(OpticalTrain opticalTrain);

    Optional<OpticalTrain> findById(String id);

    List<OpticalTrain> findAll();

    void deleteById(String id);
}
