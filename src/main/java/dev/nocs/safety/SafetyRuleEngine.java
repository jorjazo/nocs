package dev.nocs.safety;

import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

public final class SafetyRuleEngine {

    private final Clock clock;

    public SafetyRuleEngine() {
        this(Clock.systemUTC());
    }

    public SafetyRuleEngine(Clock clock) {
        this.clock = clock;
    }

    public List<TriggeredRule> evaluate(SafetyState state, List<SafetyRule> rules) {
        Instant now = clock.instant();
        List<TriggeredRule> fired = new ArrayList<>();
        for (SafetyRule rule : rules) {
            boolean active = isActive(state, rule.condition(), now);
            boolean wasLatched = state.isLatched(rule.name());
            if (active && !wasLatched) {
                state.latch(rule.name());
                fired.add(new TriggeredRule(rule, rule.condition(), now));
            } else if (!active && wasLatched) {
                state.unlatch(rule.name());
            }
        }
        return List.copyOf(fired);
    }

    private boolean isActive(SafetyState state, SafetyCondition c, Instant now) {
        return switch (c) {
            case SafetyCondition.HumidityAbove h -> anyReadingExceeds(state, "humidity", h.percent());
            case SafetyCondition.RainDetected ignored -> anyReadingTrue(state, "rain_detected");
            case SafetyCondition.AltitudeBelow a -> state.lastAltitudeDeg().map(d -> d < a.degrees()).orElse(false);
            case SafetyCondition.SensorOffline o -> isOffline(state, o, now);
        };
    }

    private boolean anyReadingExceeds(SafetyState state, String key, double threshold) {
        for (SensorReading r : state.readings().values()) {
            Double v = r.doubleValue(key);
            if (v != null && v > threshold) {
                return true;
            }
        }
        return false;
    }

    private boolean anyReadingTrue(SafetyState state, String key) {
        for (SensorReading r : state.readings().values()) {
            if (r.booleanValue(key)) {
                return true;
            }
        }
        return false;
    }

    private boolean isOffline(SafetyState state, SafetyCondition.SensorOffline o, Instant now) {
        Optional<Instant> seen = state.lastSeen(o.sensor());
        if (seen.isEmpty()) {
            return true;
        }
        return seen.get().isBefore(now.minusSeconds(o.thresholdSeconds()));
    }
}
