package dev.nocs.observatory;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

class HorizonMaskTest {

    @Test
    void emptyMaskReturnsZero() {
        HorizonMask m = HorizonMask.parse("[]");
        assertThat(m.minAltitudeAt(0)).isEqualTo(0.0);
        assertThat(m.minAltitudeAt(359)).isEqualTo(0.0);
    }

    @Test
    void singlePointMaskReturnsThatPoint() {
        HorizonMask m = HorizonMask.parse("[{\"az\":0,\"alt\":15}]");
        assertThat(m.minAltitudeAt(0)).isCloseTo(15.0, within(1e-9));
        assertThat(m.minAltitudeAt(180)).isCloseTo(15.0, within(1e-9));
    }

    @Test
    void linearlyInterpolatesBetweenPoints() {
        HorizonMask m = HorizonMask.parse("[{\"az\":0,\"alt\":10},{\"az\":90,\"alt\":20}]");
        assertThat(m.minAltitudeAt(45)).isCloseTo(15.0, within(1e-9));
        assertThat(m.minAltitudeAt(0)).isCloseTo(10.0, within(1e-9));
        assertThat(m.minAltitudeAt(90)).isCloseTo(20.0, within(1e-9));
    }

    @Test
    void wrapsAroundAt360() {
        HorizonMask m = HorizonMask.parse("[{\"az\":350,\"alt\":20},{\"az\":10,\"alt\":10}]");
        // Halfway wraps through 0.
        assertThat(m.minAltitudeAt(0)).isCloseTo(15.0, within(1e-9));
    }

    @Test
    void invalidJsonThrows() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> HorizonMask.parse("not-json"));
    }
}
