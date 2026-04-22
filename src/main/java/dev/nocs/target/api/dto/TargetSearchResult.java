package dev.nocs.target.api.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import dev.nocs.target.TargetObservation;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record TargetSearchResult(TargetView target, TargetObservation observation) {}
