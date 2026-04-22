package dev.nocs.astronomy;

import java.time.Instant;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

class PrecessionTest {

    @Test
    void j2000ToJ2000IsIdentity() {
        double[] out = Precession.precessFromJ2000(10.0, 20.0, Instant.parse("2000-01-01T12:00:00Z"));
        assertThat(out[0]).isCloseTo(10.0, within(1e-6));
        assertThat(out[1]).isCloseTo(20.0, within(1e-6));
    }

    @Test
    void precessesM31ToApprox2026() {
        // M31 J2000: RA 10.684708°, Dec 41.268751°.
        // Approximate JNow at 2026-04-22T00:00:00Z: should drift by ~few arcmin east and slightly north.
        Instant t = Instant.parse("2026-04-22T00:00:00Z");
        double[] out = Precession.precessFromJ2000(10.684708, 41.268751, t);
        // Tolerances: precession amount over 26 years is about 20' in RA.
        assertThat(out[0] - 10.684708).isBetween(0.05, 1.5); // RA drift east, degrees
        assertThat(Math.abs(out[1] - 41.268751)).isLessThan(0.2); // Dec drift < 12'
    }
}
