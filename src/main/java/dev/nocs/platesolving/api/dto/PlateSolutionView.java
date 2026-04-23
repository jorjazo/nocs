package dev.nocs.platesolving.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import dev.nocs.platesolving.PlateSolution;
import dev.nocs.platesolving.PlateSolutionRecord;
import java.time.Instant;

public record PlateSolutionView(
        @JsonProperty("ra_j2000_deg") double raJ2000Deg,
        @JsonProperty("dec_j2000_deg") double decJ2000Deg,
        @JsonProperty("pixel_scale_arcsec_per_pixel") double pixelScaleArcsecPerPx,
        @JsonProperty("rotation_deg") double rotationDeg,
        @JsonProperty("field_width_deg") double fieldWidthDeg,
        @JsonProperty("field_height_deg") double fieldHeightDeg,
        @JsonProperty("solver") String solver,
        @JsonProperty("solved_at") Instant solvedAt,
        @JsonProperty("duration_ms") long durationMs) {

    public static PlateSolutionView from(PlateSolution s, long durationMs) {
        return new PlateSolutionView(
                s.raJ2000Deg(), s.decJ2000Deg(), s.pixelScaleArcsecPerPx(),
                s.rotationDeg(), s.fieldWidthDeg(), s.fieldHeightDeg(),
                s.solver(), s.solvedAt(), durationMs);
    }

    public static PlateSolutionView fromRecord(PlateSolutionRecord r) {
        return new PlateSolutionView(
                r.raJ2000Deg(), r.decJ2000Deg(), r.pixelScaleArcsecPerPx(),
                r.rotationDeg(), r.fieldWidthDeg(), r.fieldHeightDeg(),
                r.solver(), r.solvedAt(), r.durationMs());
    }
}
