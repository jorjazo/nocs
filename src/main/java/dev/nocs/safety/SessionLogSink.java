package dev.nocs.safety;

import java.util.Map;

@FunctionalInterface
public interface SessionLogSink {

    void log(String topic, String type, Map<String, Object> payload);

    SessionLogSink NOOP = (t, ty, p) -> {};
}
