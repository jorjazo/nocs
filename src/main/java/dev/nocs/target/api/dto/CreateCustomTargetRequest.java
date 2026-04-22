package dev.nocs.target.api.dto;

public record CreateCustomTargetRequest(String name, double raJ2000Deg, double decJ2000Deg, String notes) {}
