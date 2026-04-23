package dev.nocs.safety;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SafetyRuleEngineTest {

    private final Instant now = Instant.parse("2026-04-22T10:00:00Z");
    private final Clock clock = Clock.fixed(now, ZoneOffset.UTC);
    private final SafetyRuleEngine engine = new SafetyRuleEngine(clock);

    @Test
    void humidityAboveTriggersWhenReadingExceedsThreshold() {
        SafetyState state = new SafetyState();
        state.recordReading(new SensorReading("weather", now, Map.of("humidity", 95.0)));

        SafetyRule rule = rule("hum", new SafetyCondition.HumidityAbove(90), SafetyAction.PAUSE_SEQUENCE);
        List<TriggeredRule> fired = engine.evaluate(state, List.of(rule));

        assertThat(fired).hasSize(1);
        assertThat(fired.get(0).rule()).isEqualTo(rule);
        assertThat(state.isLatched("hum")).isTrue();
    }

    @Test
    void humidityBelowThresholdDoesNotTrigger() {
        SafetyState state = new SafetyState();
        state.recordReading(new SensorReading("weather", now, Map.of("humidity", 50.0)));

        SafetyRule rule = rule("hum", new SafetyCondition.HumidityAbove(90), SafetyAction.PAUSE_SEQUENCE);
        assertThat(engine.evaluate(state, List.of(rule))).isEmpty();
    }

    @Test
    void rainDetectedTriggersOnTrueOnly() {
        SafetyState state = new SafetyState();
        SafetyRule rule = rule("rain", new SafetyCondition.RainDetected(), SafetyAction.E_STOP);

        state.recordReading(new SensorReading("weather", now, Map.of("rain_detected", false)));
        assertThat(engine.evaluate(state, List.of(rule))).isEmpty();

        state.recordReading(new SensorReading("weather", now.plusSeconds(1), Map.of("rain_detected", true)));
        assertThat(engine.evaluate(state, List.of(rule))).hasSize(1);
    }

    @Test
    void altitudeBelowTriggersOnlyWhenAltitudeKnownAndBelow() {
        SafetyState state = new SafetyState();
        SafetyRule rule = rule("alt", new SafetyCondition.AltitudeBelow(20), SafetyAction.ABORT_AND_PARK);

        assertThat(engine.evaluate(state, List.of(rule))).isEmpty();

        state.setLastAltitudeDeg(25.0);
        assertThat(engine.evaluate(state, List.of(rule))).isEmpty();

        state.setLastAltitudeDeg(15.0);
        assertThat(engine.evaluate(state, List.of(rule))).hasSize(1);
    }

    @Test
    void sensorOfflineTriggersAfterThreshold() {
        SafetyState state = new SafetyState();
        SafetyRule rule = rule("offline",
                new SafetyCondition.SensorOffline("weather", 60),
                SafetyAction.PAUSE_SEQUENCE);

        // No reading at all => offline.
        assertThat(engine.evaluate(state, List.of(rule))).hasSize(1);
        state.unlatchAll();

        // Recent reading => online.
        state.recordReading(new SensorReading("weather", now.minusSeconds(30), Map.of()));
        assertThat(engine.evaluate(state, List.of(rule))).isEmpty();

        // Stale reading => offline.
        state.recordReading(new SensorReading("weather", now.minusSeconds(120), Map.of()));
        assertThat(engine.evaluate(state, List.of(rule))).hasSize(1);
    }

    @Test
    void latchedRuleDoesNotRefireUntilConditionClears() {
        SafetyState state = new SafetyState();
        state.recordReading(new SensorReading("weather", now, Map.of("rain_detected", true)));

        SafetyRule rule = rule("rain", new SafetyCondition.RainDetected(), SafetyAction.E_STOP);

        assertThat(engine.evaluate(state, List.of(rule))).hasSize(1);
        assertThat(engine.evaluate(state, List.of(rule))).isEmpty(); // latched

        state.recordReading(new SensorReading("weather", now.plusSeconds(60), Map.of("rain_detected", false)));
        assertThat(engine.evaluate(state, List.of(rule))).isEmpty(); // clears latch but does not fire
        assertThat(state.isLatched("rain")).isFalse();

        state.recordReading(new SensorReading("weather", now.plusSeconds(120), Map.of("rain_detected", true)));
        assertThat(engine.evaluate(state, List.of(rule))).hasSize(1); // refires after clear
    }

    private SafetyRule rule(String name, SafetyCondition c, SafetyAction a) {
        return new SafetyRule(name, c, a);
    }
}
