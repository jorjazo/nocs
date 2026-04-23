package dev.nocs.safety;

public sealed interface SafetyCondition
        permits SafetyCondition.HumidityAbove,
                SafetyCondition.RainDetected,
                SafetyCondition.AltitudeBelow,
                SafetyCondition.SensorOffline {

    record HumidityAbove(double percent) implements SafetyCondition {}

    record RainDetected() implements SafetyCondition {}

    record AltitudeBelow(double degrees) implements SafetyCondition {}

    record SensorOffline(String sensor, long thresholdSeconds) implements SafetyCondition {
        public SensorOffline {
            if (sensor == null || sensor.isBlank()) {
                throw new IllegalArgumentException("sensor name is required for sensor_offline");
            }
            if (thresholdSeconds <= 0) {
                throw new IllegalArgumentException("thresholdSeconds must be positive");
            }
        }
    }

    static String wireOf(SafetyCondition c) {
        return switch (c) {
            case HumidityAbove ignored -> "humidity_above";
            case RainDetected ignored -> "rain_detected";
            case AltitudeBelow ignored -> "altitude_below";
            case SensorOffline ignored -> "sensor_offline";
        };
    }
}
