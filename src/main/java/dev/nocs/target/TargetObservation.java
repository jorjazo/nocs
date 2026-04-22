package dev.nocs.target;

import java.time.Instant;
import java.util.Optional;

public record TargetObservation(
        Instant computedAt,
        double raJNowDeg,
        double decJNowDeg,
        double altitudeDeg,
        double azimuthDeg,
        double airmass,
        Optional<Instant> transitUtc,
        Optional<Instant> riseUtc,
        Optional<Instant> setUtc,
        boolean alwaysAbove,
        boolean alwaysBelow) {}
