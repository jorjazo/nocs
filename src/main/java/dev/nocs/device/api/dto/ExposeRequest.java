package dev.nocs.device.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

public record ExposeRequest(
        double durationSeconds,
        @JsonProperty("filter") String filter,
        @JsonProperty("target") String target,
        @JsonProperty("step") String step,
        @JsonProperty("seq") Integer seq) {

    public ExposeRequest(double durationSeconds) {
        this(durationSeconds, null, null, null, null);
    }
}
