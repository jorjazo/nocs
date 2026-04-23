package dev.nocs.safety;

import java.time.Instant;
import java.util.Map;

public record SensorReading(String sensor, Instant ts, Map<String, Object> values) {

    public SensorReading {
        if (sensor == null || sensor.isBlank()) {
            throw new IllegalArgumentException("sensor name is required");
        }
        if (ts == null) {
            ts = Instant.now();
        }
        values = values == null ? Map.of() : Map.copyOf(values);
    }

    public boolean booleanValue(String key) {
        Object v = values.get(key);
        return v instanceof Boolean b && b;
    }

    public Double doubleValue(String key) {
        Object v = values.get(key);
        if (v instanceof Number n) {
            return n.doubleValue();
        }
        return null;
    }
}
