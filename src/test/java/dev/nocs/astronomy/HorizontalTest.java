package dev.nocs.astronomy;

import java.time.Instant;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

class HorizontalTest {

    @Test
    void objectAtPoleIsAlwaysAtAltitudeEqualsLatitude() {
        GeographicLocation loc = new GeographicLocation(40.0, 0.0, 0.0);
        // RA irrelevant for declination exactly at +90° (north celestial pole).
        double[] altaz = Horizontal.equatorialToHorizontal(
                10.0, 90.0, loc, Instant.parse("2026-04-22T00:00:00Z"), false);
        assertThat(altaz[0]).isCloseTo(40.0, within(1e-6)); // alt ≈ latitude
    }

    @Test
    void zenithAirmassIsOne() {
        assertThat(Horizontal.airmass(90.0)).isCloseTo(1.0, within(1e-3));
    }

    @Test
    void airmassAt30DegAltIsTwo() {
        // sec(60°) = 2
        assertThat(Horizontal.airmass(30.0)).isCloseTo(2.0, within(0.05));
    }

    @Test
    void refractionRaisesLowObject() {
        // Apparent altitude of object at geometric 0° rises ~34' due to refraction.
        double apparent = Horizontal.applyRefraction(0.0);
        assertThat(apparent - 0.0).isBetween(0.4, 0.8);
    }

    @Test
    void refractionHasNoEffectAtZenith() {
        assertThat(Horizontal.applyRefraction(89.9)).isCloseTo(89.9, within(1e-3));
    }
}
