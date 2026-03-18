package dev.nocs.service;

import dev.nocs.domain.DeviceReference;
import dev.nocs.domain.OpticalTrain;
import dev.nocs.repository.OpticalTrainRepository;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

/**
 * CRUD operations for optical trains.
 */
@Service
public class OpticalTrainService {

    private final OpticalTrainRepository opticalTrainRepository;

    public OpticalTrainService(OpticalTrainRepository opticalTrainRepository) {
        this.opticalTrainRepository = opticalTrainRepository;
    }

    public List<OpticalTrain> findAll() {
        return opticalTrainRepository.findAll();
    }

    public Optional<OpticalTrain> findById(String id) {
        return opticalTrainRepository.findById(id);
    }

    public OpticalTrain create(String name, double focalLengthMm, Double apertureMm,
                              DeviceReference camera, DeviceReference focuser, DeviceReference filterWheel) {
        OpticalTrain train = new OpticalTrain(
                UUID.randomUUID().toString(),
                name,
                focalLengthMm,
                apertureMm,
                camera,
                focuser,
                filterWheel);
        return opticalTrainRepository.save(train);
    }

    public Optional<OpticalTrain> update(String id, String name, Double focalLengthMm, Double apertureMm,
                                        DeviceReference camera, DeviceReference focuser, DeviceReference filterWheel) {
        return opticalTrainRepository.findById(id)
                .map(t -> {
                    OpticalTrain updated = new OpticalTrain(
                            t.id(),
                            name != null ? name : t.name(),
                            focalLengthMm != null ? focalLengthMm : t.focalLengthMm(),
                            apertureMm != null ? apertureMm : t.apertureMm(),
                            camera != null ? camera : t.camera(),
                            focuser != null ? focuser : t.focuser(),
                            filterWheel != null ? filterWheel : t.filterWheel());
                    return opticalTrainRepository.save(updated);
                });
    }

    public void deleteById(String id) {
        opticalTrainRepository.deleteById(id);
    }
}
