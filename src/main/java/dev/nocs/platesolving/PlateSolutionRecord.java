package dev.nocs.platesolving;

import java.time.Instant;

public record PlateSolutionRecord(
        Long id,
        long imageId,
        double raJ2000Deg,
        double decJ2000Deg,
        double pixelScaleArcsecPerPx,
        double rotationDeg,
        double fieldWidthDeg,
        double fieldHeightDeg,
        long durationMs,
        String solver,
        Instant solvedAt) {

    public static PlateSolutionRecord forInsert(
            long imageId,
            double raJ2000Deg,
            double decJ2000Deg,
            double pixelScaleArcsecPerPx,
            double rotationDeg,
            double fieldWidthDeg,
            double fieldHeightDeg,
            long durationMs,
            String solver,
            Instant solvedAt) {
        return new PlateSolutionRecord(
                null, imageId, raJ2000Deg, decJ2000Deg,
                pixelScaleArcsecPerPx, rotationDeg, fieldWidthDeg, fieldHeightDeg,
                durationMs, solver == null ? "unknown" : solver,
                solvedAt == null ? Instant.now() : solvedAt);
    }

    public static PlateSolutionRecord fromSolution(long imageId, PlateSolution s, long durationMs) {
        return forInsert(
                imageId,
                s.raJ2000Deg(),
                s.decJ2000Deg(),
                s.pixelScaleArcsecPerPx(),
                s.rotationDeg(),
                s.fieldWidthDeg(),
                s.fieldHeightDeg(),
                durationMs,
                s.solver(),
                s.solvedAt());
    }
}
