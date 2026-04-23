package dev.nocs.safety.api.dto;

import dev.nocs.safety.SafetyCondition;
import dev.nocs.safety.SafetyRule;
import java.util.LinkedHashMap;
import java.util.Map;

public record RuleView(String name, String action, Map<String, Object> when, boolean latched) {

    public static RuleView of(SafetyRule rule, boolean latched) {
        return new RuleView(rule.name(), rule.action().wire(), conditionMap(rule.condition()), latched);
    }

    private static Map<String, Object> conditionMap(SafetyCondition c) {
        Map<String, Object> out = new LinkedHashMap<>();
        switch (c) {
            case SafetyCondition.HumidityAbove h -> out.put("humidity_above", h.percent());
            case SafetyCondition.RainDetected ignored -> out.put("rain_detected", true);
            case SafetyCondition.AltitudeBelow a -> out.put("altitude_below", a.degrees());
            case SafetyCondition.SensorOffline o -> out.put(
                    "sensor_offline", Map.of("sensor", o.sensor(), "threshold_seconds", o.thresholdSeconds()));
        }
        return out;
    }
}
