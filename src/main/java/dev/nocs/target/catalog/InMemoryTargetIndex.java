package dev.nocs.target.catalog;

import dev.nocs.target.Target;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Collectors;

public final class InMemoryTargetIndex {

    private final List<Target> all;
    private final Map<String, Target> byId;

    public InMemoryTargetIndex(List<Target> targets) {
        this.all = List.copyOf(targets);
        this.byId = new HashMap<>();
        for (Target t : targets) byId.put(t.id(), t);
    }

    public Optional<Target> findById(String id) {
        return Optional.ofNullable(byId.get(id));
    }

    public int size() {
        return all.size();
    }

    public List<Target> all() {
        return all;
    }

    /**
     * Rank:
     *   0 — exact alias or primary-name match
     *   1 — starts-with
     *   2 — contains
     * Targets with no match are dropped. Ties break by primary-name length (shorter first).
     */
    public List<Target> search(String queryRaw, int limit) {
        if (queryRaw == null) return List.of();
        String q = queryRaw.trim().toLowerCase();
        if (q.isEmpty()) return List.of();

        return all.stream()
                .map(t -> new Ranked(t, rank(t, q)))
                .filter(r -> r.rank < 3)
                .sorted(Comparator.<Ranked>comparingInt(r -> r.rank)
                        .thenComparingInt(r -> r.target.primaryName().length()))
                .limit(limit <= 0 ? Long.MAX_VALUE : limit)
                .map(r -> r.target)
                .collect(Collectors.toList());
    }

    private int rank(Target t, String q) {
        String name = t.primaryName().toLowerCase();
        if (name.equals(q)) return 0;
        for (String a : t.aliases()) if (a.toLowerCase().equals(q)) return 0;
        if (name.startsWith(q)) return 1;
        for (String a : t.aliases()) if (a.toLowerCase().startsWith(q)) return 1;
        if (name.contains(q)) return 2;
        for (String a : t.aliases()) if (a.toLowerCase().contains(q)) return 2;
        return 3;
    }

    private record Ranked(Target target, int rank) {}
}
