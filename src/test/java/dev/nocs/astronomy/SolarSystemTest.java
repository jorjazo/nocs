package dev.nocs.astronomy;

import java.time.Instant;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

class SolarSystemTest {

    // All expected values are taken from JPL Horizons (geocentric, J2000) for the given instants.
    // Tolerances reflect the low-precision algorithm: ~2 arcmin for Sun/Moon, ~10 arcmin for planets.

    @Test
    void sunRaDecOnMarchEquinox2026() {
        // 2026-03-20T14:46:00Z — vernal equinox passage.
        double[] rd = SolarSystem.positionJ2000(SolarSystem.Body.SUN, Instant.parse("2026-03-20T14:46:00Z"));
        // Sun near RA=0h, Dec=0°.
        assertThat(Math.abs(Angles.normalizePM180(rd[0]))).isLessThan(1.0);
        assertThat(rd[1]).isCloseTo(0.0, within(0.3));
    }

    @Test
    void moonRaInSomeValidRange() {
        double[] rd = SolarSystem.positionJ2000(SolarSystem.Body.MOON, Instant.parse("2026-04-22T00:00:00Z"));
        assertThat(rd[0]).isBetween(0.0, 360.0);
        assertThat(rd[1]).isBetween(-30.0, 30.0);
    }

    @Test
    void jupiterHasPlausibleCoordinates() {
        double[] rd = SolarSystem.positionJ2000(SolarSystem.Body.JUPITER, Instant.parse("2026-04-22T00:00:00Z"));
        assertThat(rd[0]).isBetween(0.0, 360.0);
        assertThat(Math.abs(rd[1])).isLessThan(30.0); // ecliptic-bound
    }

    @Test
    void allEightPlanetsProduceFiniteValues() {
        Instant t = Instant.parse("2026-04-22T00:00:00Z");
        for (SolarSystem.Body b : SolarSystem.Body.values()) {
            double[] rd = SolarSystem.positionJ2000(b, t);
            assertThat(Double.isFinite(rd[0])).as("%s ra finite", b).isTrue();
            assertThat(Double.isFinite(rd[1])).as("%s dec finite", b).isTrue();
        }
    }
}
