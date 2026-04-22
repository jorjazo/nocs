package dev.nocs.astronomy;

import java.time.Duration;
import java.time.Instant;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

class RiseTransitSetTest {

    @Test
    void transitIsBetweenRiseAndSetForVisibleObject() {
        // An observer at 0° lat, 0° lon, and an object at RA 0°, Dec 0°:
        // transit occurs when LST = 0h. At midnight UTC 2026-03-20, LST(0 lon) ≈ 0h too (equinox-ish).
        Instant t = Instant.parse("2026-03-20T00:00:00Z");
        GeographicLocation loc = new GeographicLocation(0.0, 0.0, 0.0);
        RiseTransitSet.Result r = RiseTransitSet.compute(0.0, 0.0, loc, t);
        assertThat(r.transit()).isPresent();
        assertThat(r.rise()).isPresent();
        assertThat(r.set()).isPresent();
        Instant rise = r.rise().get(), transit = r.transit().get(), set = r.set().get();
        assertThat(rise).isBefore(transit);
        assertThat(transit).isBefore(set);
    }

    @Test
    void circumpolarObjectHasNoRiseOrSet() {
        // North celestial pole from lat +60°: never sets.
        Instant t = Instant.parse("2026-04-22T00:00:00Z");
        GeographicLocation loc = new GeographicLocation(60.0, 0.0, 0.0);
        RiseTransitSet.Result r = RiseTransitSet.compute(10.0, 89.0, loc, t);
        assertThat(r.rise()).isEmpty();
        assertThat(r.set()).isEmpty();
        assertThat(r.transit()).isPresent();
    }

    @Test
    void neverRisesBelowSouthernHorizon() {
        // SCP from lat +60°: never rises.
        Instant t = Instant.parse("2026-04-22T00:00:00Z");
        GeographicLocation loc = new GeographicLocation(60.0, 0.0, 0.0);
        RiseTransitSet.Result r = RiseTransitSet.compute(10.0, -89.0, loc, t);
        assertThat(r.rise()).isEmpty();
        assertThat(r.set()).isEmpty();
        assertThat(r.alwaysBelow()).isTrue();
    }

    @Test
    void transitWithinOneSiderealDay() {
        Instant t = Instant.parse("2026-04-22T00:00:00Z");
        GeographicLocation loc = new GeographicLocation(40.0, -74.0, 10.0);
        RiseTransitSet.Result r = RiseTransitSet.compute(10.684708, 41.268751, loc, t);
        Instant transit = r.transit().orElseThrow();
        Duration delta = Duration.between(t, transit).abs();
        assertThat(delta).isLessThan(Duration.ofHours(24));
    }
}
