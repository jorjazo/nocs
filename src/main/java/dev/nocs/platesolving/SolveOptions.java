package dev.nocs.platesolving;

public record SolveOptions(
        Double raHintDeg,
        Double decHintDeg,
        Double radiusDeg,
        Double pixelScaleArcsecPerPxHint,
        Double timeoutSec) {

    public SolveOptions {
        if (radiusDeg != null && radiusDeg < 0) {
            throw new IllegalArgumentException("radiusDeg must be >= 0, got " + radiusDeg);
        }
        if (pixelScaleArcsecPerPxHint != null && pixelScaleArcsecPerPxHint <= 0) {
            throw new IllegalArgumentException("pixelScaleArcsecPerPxHint must be > 0");
        }
        if (timeoutSec != null && timeoutSec <= 0) {
            throw new IllegalArgumentException("timeoutSec must be > 0");
        }
    }

    public static SolveOptions defaults() {
        return new SolveOptions(null, null, null, null, null);
    }

    public SolveOptions withTimeout(double seconds) {
        return new SolveOptions(raHintDeg, decHintDeg, radiusDeg, pixelScaleArcsecPerPxHint, seconds);
    }
}
