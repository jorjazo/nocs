package dev.nocs.platesolving.api.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record SolveResponse(
        @JsonProperty("solved") boolean solved,
        @JsonProperty("image_id") Long imageId,
        @JsonProperty("solution") PlateSolutionView solution,
        @JsonProperty("failure_kind") String failureKind,
        @JsonProperty("message") String message,
        @JsonProperty("duration_ms") long durationMs) {

    public static SolveResponse success(long imageId, PlateSolutionView v) {
        return new SolveResponse(true, imageId, v, null, null, v.durationMs());
    }

    public static SolveResponse failure(long imageId, String failureKind, String message, long durationMs) {
        return new SolveResponse(false, imageId, null, failureKind, message, durationMs);
    }
}
