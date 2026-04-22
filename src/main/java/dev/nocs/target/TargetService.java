package dev.nocs.target;

import dev.nocs.astronomy.GeographicLocation;
import dev.nocs.astronomy.Horizontal;
import dev.nocs.astronomy.Precession;
import dev.nocs.astronomy.RiseTransitSet;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.observatory.ObservatoryService;
import dev.nocs.target.catalog.InMemoryTargetIndex;
import dev.nocs.target.catalog.SolarSystemCatalog;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.stereotype.Service;

@Service
public class TargetService {

    private final InMemoryTargetIndex bundled;
    private final TargetRepository custom;
    private final ObservatoryService observatoryService;
    private final SimbadResolver simbad;
    private final EventBus bus;

    public TargetService(
            InMemoryTargetIndex bundled,
            TargetRepository custom,
            ObservatoryService observatoryService,
            SimbadResolver simbad,
            EventBus bus) {
        this.bundled = bundled;
        this.custom = custom;
        this.observatoryService = observatoryService;
        this.simbad = simbad;
        this.bus = bus;
    }

    public record Resolved(Target target, Optional<TargetObservation> observation) {}

    public List<Resolved> search(String query, int limit) {
        Instant now = Instant.now();
        Map<String, Target> results = new LinkedHashMap<>();
        for (Target t : bundled.search(query, limit)) results.put(t.id(), t);
        for (Target t : SolarSystemCatalog.search(query, now, limit)) results.put(t.id(), t);
        for (Target t : custom.findAll()) {
            if (matches(t, query)) results.put(t.id(), t);
        }
        if (results.isEmpty() && simbad != null) {
            simbad.resolve(query).ifPresent(t -> results.put(t.id(), t));
        }
        return trim(results.values(), limit).stream()
                .map(t -> new Resolved(t, observation(t, now)))
                .toList();
    }

    public Optional<Resolved> resolveById(String id, Instant when) {
        TargetId.Parsed p = TargetId.parse(id);
        if (p.catalog().equals("custom")) {
            try {
                long numeric = Long.parseLong(p.designator());
                return custom.findById(numeric).map(t -> new Resolved(t, observation(t, when)));
            } catch (NumberFormatException e) {
                return Optional.empty();
            }
        }
        if (p.catalog().equals("sun") || p.catalog().equals("moon") || p.catalog().equals("planet")) {
            return SolarSystemCatalog.resolveWithPosition(id, when)
                    .map(t -> new Resolved(t, observation(t, when)));
        }
        return bundled.findById(id).map(t -> new Resolved(t, observation(t, when)));
    }

    public long addCustom(String name, double ra, double dec, String notes) {
        long id = custom.insert(name, ra, dec, TargetKind.CUSTOM, notes);
        bus.publish(Event.of(Topic.SYSTEM, "target_custom_added", Map.of("id", id, "name", name)));
        return id;
    }

    public boolean deleteCustom(long id) {
        boolean removed = custom.delete(id);
        if (removed) bus.publish(Event.of(Topic.SYSTEM, "target_custom_deleted", Map.of("id", id)));
        return removed;
    }

    public Optional<TargetObservation> observation(Target t, Instant when) {
        if (!t.hasFixedCoordinates()) return Optional.empty();
        Optional<GeographicLocation> loc = observatoryService.activeLocation();
        if (loc.isEmpty()) return Optional.empty();
        double[] jnow = Precession.precessFromJ2000(t.raJ2000Deg(), t.decJ2000Deg(), when);
        double[] altaz = Horizontal.equatorialToHorizontal(jnow[0], jnow[1], loc.get(), when, true);
        double airmass = Horizontal.airmass(altaz[0]);
        RiseTransitSet.Result rts = RiseTransitSet.compute(jnow[0], jnow[1], loc.get(), when);
        return Optional.of(new TargetObservation(
                when, jnow[0], jnow[1], altaz[0], altaz[1], airmass,
                rts.transit(), rts.rise(), rts.set(),
                rts.alwaysAbove(), rts.alwaysBelow()));
    }

    private static boolean matches(Target t, String query) {
        if (query == null || query.isBlank()) return false;
        String q = query.toLowerCase();
        if (t.primaryName().toLowerCase().contains(q)) return true;
        for (String a : t.aliases()) if (a.toLowerCase().contains(q)) return true;
        return false;
    }

    private static List<Target> trim(Iterable<Target> input, int limit) {
        List<Target> out = new ArrayList<>();
        for (Target t : input) {
            out.add(t);
            if (limit > 0 && out.size() >= limit) break;
        }
        return out;
    }
}
