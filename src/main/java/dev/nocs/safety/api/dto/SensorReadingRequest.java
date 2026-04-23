package dev.nocs.safety.api.dto;

import java.time.Instant;
import java.util.Map;

public record SensorReadingRequest(String sensor, Instant ts, Map<String, Object> values) {}
