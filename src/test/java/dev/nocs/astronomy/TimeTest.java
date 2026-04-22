package dev.nocs.astronomy;

import java.time.Instant;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

class TimeTest {

    @Test
    void julianDateMatchesMeeusExample() {
        // Meeus, Astronomical Algorithms, example 7.a: 1957 Oct 4.81 UT → JD 2436116.31.
        Instant t = Instant.parse("1957-10-04T19:26:24Z");
        double jd = Time.julianDay(t);
        assertThat(jd).isCloseTo(2436116.31, within(1e-2));
    }

    @Test
    void gmstAtJ2000IsAbout18h697h() {
        // At J2000.0 (2000-01-01T12:00:00Z), GMST ≈ 18h 41m 50.548s = 280.4606°.
        double gmst = Time.gmstDeg(Instant.parse("2000-01-01T12:00:00Z"));
        assertThat(gmst).isCloseTo(280.4606, within(1e-2));
    }

    @Test
    void lstAtGreenwichEqualsGmst() {
        Instant t = Instant.parse("2026-04-22T00:00:00Z");
        double gmst = Time.gmstDeg(t);
        double lst = Time.lstDeg(t, 0.0);
        assertThat(lst).isCloseTo(gmst, within(1e-6));
    }

    @Test
    void lstAdvancesWithEastLongitude() {
        Instant t = Instant.parse("2026-04-22T00:00:00Z");
        double lst0 = Time.lstDeg(t, 0.0);
        double lst90 = Time.lstDeg(t, 90.0);
        assertThat(Angles.normalize360(lst90 - lst0)).isCloseTo(90.0, within(1e-6));
    }
}
