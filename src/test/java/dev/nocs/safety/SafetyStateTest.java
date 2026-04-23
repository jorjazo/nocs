package dev.nocs.safety;

import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SafetyStateTest {

    @Test
    void recordsMostRecentReadingPerSensor() {
        SafetyState state = new SafetyState();

        state.recordReading(new SensorReading("weather", Instant.parse("2026-04-22T10:00:00Z"),
                Map.of("humidity", 80.0, "rain_detected", false)));
        state.recordReading(new SensorReading("weather", Instant.parse("2026-04-22T10:01:00Z"),
                Map.of("humidity", 92.0, "rain_detected", true)));

        assertThat(state.lastReading("weather")).isPresent();
        assertThat(state.lastReading("weather").get().values().get("humidity")).isEqualTo(92.0);
        assertThat(state.lastSeen("weather")).hasValue(Instant.parse("2026-04-22T10:01:00Z"));
        assertThat(state.lastReading("missing")).isEmpty();
    }

    @Test
    void tracksActiveTarget() {
        SafetyState state = new SafetyState();
        ActiveTarget t = new ActiveTarget("messier:M31", 10.685, 41.269, Instant.now());

        assertThat(state.activeTarget()).isEmpty();
        state.setActiveTarget(t);
        assertThat(state.activeTarget()).hasValue(t);
        state.setActiveTarget(null);
        assertThat(state.activeTarget()).isEmpty();
    }

    @Test
    void tracksLatchPerRule() {
        SafetyState state = new SafetyState();

        assertThat(state.isLatched("rain")).isFalse();
        state.latch("rain");
        assertThat(state.isLatched("rain")).isTrue();
        state.unlatch("rain");
        assertThat(state.isLatched("rain")).isFalse();

        state.latch("a");
        state.latch("b");
        state.unlatchAll();
        assertThat(state.isLatched("a")).isFalse();
        assertThat(state.isLatched("b")).isFalse();
    }

    @Test
    void cachesLatestAltitudeForActiveTarget() {
        SafetyState state = new SafetyState();
        assertThat(state.lastAltitudeDeg()).isEmpty();
        state.setLastAltitudeDeg(15.5);
        assertThat(state.lastAltitudeDeg()).hasValue(15.5);
    }
}
