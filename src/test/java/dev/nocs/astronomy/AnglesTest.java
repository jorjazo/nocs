package dev.nocs.astronomy;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

class AnglesTest {

    @Test
    void normalizeDegWrapsTo0to360() {
        assertThat(Angles.normalize360(720.5)).isCloseTo(0.5, within(1e-9));
        assertThat(Angles.normalize360(-1.0)).isCloseTo(359.0, within(1e-9));
    }

    @Test
    void normalizeDegPMWrapsToMinus180to180() {
        assertThat(Angles.normalizePM180(190.0)).isCloseTo(-170.0, within(1e-9));
        assertThat(Angles.normalizePM180(-200.0)).isCloseTo(160.0, within(1e-9));
    }

    @Test
    void hmsParsesHoursToDegrees() {
        double ra = Angles.parseHmsToDeg("0h 42m 44.3s");
        // M31 RA ≈ 10.684708°
        assertThat(ra).isCloseTo(10.6846, within(1e-3));
    }

    @Test
    void dmsParsesDegrees() {
        double dec = Angles.parseDmsToDeg("+41° 16′ 08″");
        assertThat(dec).isCloseTo(41.2689, within(1e-3));
        assertThat(Angles.parseDmsToDeg("-12:30:00")).isCloseTo(-12.5, within(1e-9));
    }
}
