package dev.nocs.safety;

import java.time.Instant;

public record ActiveTarget(String targetId, double raJ2000Deg, double decJ2000Deg, Instant since) {

    public ActiveTarget {
        if (targetId == null || targetId.isBlank()) {
            throw new IllegalArgumentException("targetId is required");
        }
        if (Double.isNaN(raJ2000Deg) || Double.isNaN(decJ2000Deg)) {
            throw new IllegalArgumentException("ra/dec must be numeric");
        }
        if (since == null) {
            since = Instant.now();
        }
    }
}
