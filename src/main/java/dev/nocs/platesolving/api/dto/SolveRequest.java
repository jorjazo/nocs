package dev.nocs.platesolving.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

public record SolveRequest(
        @JsonProperty("image_id") Long imageId,
        @JsonProperty("ra_hint_hours") Double raHintHours,
        @JsonProperty("dec_hint_deg") Double decHintDeg,
        @JsonProperty("radius_deg") Double radiusDeg,
        @JsonProperty("scale_hint_arcsec_per_pixel") Double scaleHintArcsecPerPx,
        @JsonProperty("timeout_sec") Double timeoutSec) {}
