package dev.nocs.target.catalog;

import dev.nocs.astronomy.SolarSystem;
import dev.nocs.target.Target;
import dev.nocs.target.TargetKind;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;

public final class SolarSystemCatalog {

    private static final Map<String, SolarSystem.Body> ID_TO_BODY = Map.ofEntries(
            Map.entry("sun", SolarSystem.Body.SUN),
            Map.entry("moon", SolarSystem.Body.MOON),
            Map.entry("planet:mercury", SolarSystem.Body.MERCURY),
            Map.entry("planet:venus", SolarSystem.Body.VENUS),
            Map.entry("planet:mars", SolarSystem.Body.MARS),
            Map.entry("planet:jupiter", SolarSystem.Body.JUPITER),
            Map.entry("planet:saturn", SolarSystem.Body.SATURN),
            Map.entry("planet:uranus", SolarSystem.Body.URANUS),
            Map.entry("planet:neptune", SolarSystem.Body.NEPTUNE),
            Map.entry("planet:pluto", SolarSystem.Body.PLUTO));

    private SolarSystemCatalog() {}

    /** Static "shell" targets — no position baked in; callers use {@link #resolveWithPosition}. */
    public static List<Target> staticTargets() {
        List<Target> out = new ArrayList<>();
        for (Map.Entry<String, SolarSystem.Body> e : ID_TO_BODY.entrySet()) {
            out.add(shell(e.getKey(), e.getValue()));
        }
        return out;
    }

    public static Optional<Target> resolveWithPosition(String id, Instant when) {
        SolarSystem.Body body = ID_TO_BODY.get(id.toLowerCase(Locale.ROOT));
        if (body == null) return Optional.empty();
        double[] rd = SolarSystem.positionJ2000(body, when);
        Target sh = shell(id, body);
        return Optional.of(new Target(
                sh.id(), sh.primaryName(), sh.aliases(), sh.kind(),
                rd[0], rd[1], "", Double.NaN, Double.NaN, "live ephemeris"));
    }

    public static List<Target> search(String queryRaw, Instant when, int limit) {
        String q = queryRaw == null ? "" : queryRaw.trim().toLowerCase(Locale.ROOT);
        if (q.isEmpty()) return List.of();
        List<Target> matches = new ArrayList<>();
        for (Map.Entry<String, SolarSystem.Body> e : ID_TO_BODY.entrySet()) {
            Target sh = shell(e.getKey(), e.getValue());
            if (sh.primaryName().toLowerCase(Locale.ROOT).contains(q)
                    || sh.id().toLowerCase(Locale.ROOT).contains(q)) {
                resolveWithPosition(e.getKey(), when).ifPresent(matches::add);
                if (matches.size() >= Math.max(1, limit)) break;
            }
        }
        return matches;
    }

    private static Target shell(String id, SolarSystem.Body body) {
        TargetKind kind = switch (body) {
            case SUN -> TargetKind.SUN;
            case MOON -> TargetKind.MOON;
            default -> TargetKind.PLANET;
        };
        String name = switch (body) {
            case SUN -> "Sun";
            case MOON -> "Moon";
            default -> body.name().charAt(0) + body.name().substring(1).toLowerCase(Locale.ROOT);
        };
        return new Target(id, name, List.of(name.toLowerCase(Locale.ROOT)), kind,
                Double.NaN, Double.NaN, "", Double.NaN, Double.NaN, "");
    }
}
