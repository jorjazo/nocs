package dev.nocs.safety;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

public final class SafetyRuleParser {

    private static final ObjectMapper YAML = new ObjectMapper(new YAMLFactory());

    public List<SafetyRule> parse(InputStream in) {
        try {
            byte[] bytes = in.readAllBytes();
            return parseString(new String(bytes, StandardCharsets.UTF_8));
        } catch (IOException e) {
            throw new IllegalArgumentException("failed to read safety rules: " + e.getMessage(), e);
        }
    }

    @SuppressWarnings("unchecked")
    public List<SafetyRule> parseString(String yaml) {
        if (yaml == null || yaml.isBlank()) {
            return List.of();
        }
        if (nonCommentContent(yaml).isBlank()) {
            return List.of();
        }
        Map<String, Object> root;
        try {
            root = YAML.readValue(yaml, Map.class);
        } catch (IOException e) {
            throw new IllegalArgumentException("invalid safety YAML: " + e.getMessage(), e);
        }
        if (root == null) {
            return List.of();
        }
        Object rulesNode = root.get("rules");
        if (rulesNode == null) {
            return List.of();
        }
        if (!(rulesNode instanceof List<?> rawRules)) {
            throw new IllegalArgumentException("'rules' must be a list");
        }
        List<SafetyRule> out = new ArrayList<>(rawRules.size());
        for (int i = 0; i < rawRules.size(); i++) {
            Object raw = rawRules.get(i);
            if (!(raw instanceof Map<?, ?> map)) {
                throw new IllegalArgumentException("rule[" + i + "] must be a map");
            }
            out.add(toRule(i, map));
        }
        return List.copyOf(out);
    }

    private SafetyRule toRule(int idx, Map<?, ?> raw) {
        Object name = raw.get("name");
        if (!(name instanceof String s) || s.isBlank()) {
            throw new IllegalArgumentException("rule[" + idx + "].name is required");
        }
        Object whenNode = raw.get("when");
        if (whenNode == null) {
            throw new IllegalArgumentException("rule[" + idx + "].when is required");
        }
        Object thenNode = raw.get("then");
        if (thenNode == null) {
            throw new IllegalArgumentException("rule[" + idx + "].then is required");
        }
        SafetyCondition condition = toCondition(idx, whenNode);
        SafetyAction action = SafetyAction.fromWire(thenNode.toString());
        return new SafetyRule(s, condition, action);
    }

    private SafetyCondition toCondition(int idx, Object node) {
        if (!(node instanceof Map<?, ?> map) || map.size() != 1) {
            throw new IllegalArgumentException(
                    "rule[" + idx + "].when must be a single-key map (humidity_above|rain_detected|altitude_below|sensor_offline)");
        }
        Map.Entry<?, ?> e = map.entrySet().iterator().next();
        String key = String.valueOf(e.getKey());
        Object val = e.getValue();
        return switch (key) {
            case "humidity_above" -> new SafetyCondition.HumidityAbove(asDouble(idx, key, val));
            case "rain_detected" -> {
                if (!Boolean.TRUE.equals(val)) {
                    throw new IllegalArgumentException("rule[" + idx + "].when.rain_detected must be true");
                }
                yield new SafetyCondition.RainDetected();
            }
            case "altitude_below" -> new SafetyCondition.AltitudeBelow(asDouble(idx, key, val));
            case "sensor_offline" -> {
                if (!(val instanceof Map<?, ?> sub)) {
                    throw new IllegalArgumentException(
                            "rule[" + idx + "].when.sensor_offline must be {sensor, threshold_seconds}");
                }
                Object sensor = sub.get("sensor");
                Object threshold = sub.get("threshold_seconds");
                if (!(sensor instanceof String ss) || ss.isBlank()) {
                    throw new IllegalArgumentException(
                            "rule[" + idx + "].when.sensor_offline.sensor is required");
                }
                yield new SafetyCondition.SensorOffline(ss, asLong(idx, "threshold_seconds", threshold));
            }
            default -> throw new IllegalArgumentException(
                    "rule[" + idx + "].when has unknown condition: " + key);
        };
    }

    private double asDouble(int idx, String key, Object val) {
        if (val instanceof Number n) {
            return n.doubleValue();
        }
        throw new IllegalArgumentException("rule[" + idx + "]." + key + " must be a number, got: " + val);
    }

    private long asLong(int idx, String key, Object val) {
        if (val instanceof Number n) {
            return n.longValue();
        }
        throw new IllegalArgumentException("rule[" + idx + "]." + key + " must be a number, got: " + val);
    }

    /** Lines that are empty or only # comments, joined back — empty means no document body. */
    private static String nonCommentContent(String yaml) {
        return Arrays.stream(yaml.split("\\R"))
                .map(String::strip)
                .filter(line -> !line.isEmpty() && !line.startsWith("#"))
                .collect(Collectors.joining("\n"));
    }
}
