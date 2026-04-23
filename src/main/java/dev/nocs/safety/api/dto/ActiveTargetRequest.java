package dev.nocs.safety.api.dto;

public record ActiveTargetRequest(String targetId, double raJ2000Deg, double decJ2000Deg) {}
