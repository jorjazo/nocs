package dev.nocs.observatory;

import dev.nocs.astronomy.GeographicLocation;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ObservatoryService {

    private final ObservatoryRepository repo;
    private final EventBus bus;

    public ObservatoryService(ObservatoryRepository repo, EventBus bus) {
        this.repo = repo;
        this.bus = bus;
    }

    public List<Observatory> list() {
        return repo.findAll();
    }

    public Optional<Observatory> find(long id) {
        return repo.findById(id);
    }

    public Optional<Observatory> active() {
        return repo.findActive();
    }

    public Optional<GeographicLocation> activeLocation() {
        return active().map(Observatory::location);
    }

    @Transactional
    public Observatory create(String name, double lat, double lon, double elev, String tz, String horizonMaskJson) {
        HorizonMask.parse(horizonMaskJson); // validate
        boolean makeActive = repo.findActive().isEmpty();
        if (makeActive) repo.deactivateAll();
        long id = repo.insert(name, lat, lon, elev, tz, horizonMaskJson, makeActive);
        Observatory created = repo.findById(id).orElseThrow();
        bus.publish(Event.of(Topic.SYSTEM, "observatory_created", Map.of("id", id, "name", name)));
        return created;
    }

    @Transactional
    public Observatory update(long id, String name, double lat, double lon, double elev, String tz, String horizonMaskJson) {
        HorizonMask.parse(horizonMaskJson);
        repo.update(id, name, lat, lon, elev, tz, horizonMaskJson);
        Observatory updated = repo.findById(id).orElseThrow();
        bus.publish(Event.of(Topic.SYSTEM, "observatory_updated", Map.of("id", id)));
        return updated;
    }

    @Transactional
    public void activate(long id) {
        repo.findById(id).orElseThrow(() -> new IllegalArgumentException("unknown observatory: " + id));
        repo.deactivateAll();
        repo.activate(id);
        bus.publish(Event.of(Topic.SYSTEM, "observatory_activated", Map.of("id", id)));
    }

    @Transactional
    public void delete(long id) {
        repo.delete(id);
        bus.publish(Event.of(Topic.SYSTEM, "observatory_deleted", Map.of("id", id)));
    }
}
