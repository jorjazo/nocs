package dev.nocs.events;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.time.Instant;
import java.util.Map;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record Event(Topic topic, String type, Instant ts, Map<String, Object> payload) {

    public static Event of(Topic topic, String type, Map<String, Object> payload) {
        return new Event(topic, type, Instant.now(), payload);
    }
}
