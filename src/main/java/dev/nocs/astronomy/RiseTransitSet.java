package dev.nocs.astronomy;

import java.time.Instant;
import java.util.Optional;

/**
 * Transit / rise / set for a fixed equatorial position (equator of date).
 * Computes the next transit at or after `referenceTime`, and the rise/set
 * bracketing that transit. Rise/set use an altitude of -0.5667° (refraction
 * at horizon per Meeus §15).
 */
public final class RiseTransitSet {

    private static final double H0_DEG = -0.5667;

    private RiseTransitSet() {}

    public record Result(
            Optional<Instant> rise,
            Optional<Instant> transit,
            Optional<Instant> set,
            boolean alwaysAbove,
            boolean alwaysBelow) {}

    public static Result compute(double raDeg, double decDeg, GeographicLocation loc, Instant referenceTime) {
        double lst = Time.lstDeg(referenceTime, loc.longitudeDeg());
        double haTransit = Angles.normalizePM180(raDeg - lst);
        // Convert hour-angle degrees to sidereal hours then to clock seconds:
        //   1 sidereal day = 86164.0905 s of UT.
        double transitOffsetSec = haTransit / 360.0 * 86164.0905;
        if (transitOffsetSec < 0) transitOffsetSec += 86164.0905;
        Instant transit = referenceTime.plusMillis((long) (transitOffsetSec * 1000.0));

        double lat = Math.toRadians(loc.latitudeDeg());
        double dec = Math.toRadians(decDeg);
        double cosH0 = (Math.sin(Math.toRadians(H0_DEG)) - Math.sin(lat) * Math.sin(dec))
                / (Math.cos(lat) * Math.cos(dec));
        if (cosH0 < -1.0) {
            return new Result(Optional.empty(), Optional.of(transit), Optional.empty(), true, false);
        }
        if (cosH0 > 1.0) {
            return new Result(Optional.empty(), Optional.of(transit), Optional.empty(), false, true);
        }
        double h0Deg = Math.toDegrees(Math.acos(cosH0));
        double halfSpanSec = h0Deg / 360.0 * 86164.0905;
        Instant rise = transit.minusMillis((long) (halfSpanSec * 1000.0));
        Instant set = transit.plusMillis((long) (halfSpanSec * 1000.0));
        return new Result(Optional.of(rise), Optional.of(transit), Optional.of(set), false, false);
    }
}
