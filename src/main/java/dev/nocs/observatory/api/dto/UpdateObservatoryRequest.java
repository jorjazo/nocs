package dev.nocs.observatory.api.dto;

public record UpdateObservatoryRequest(
        String name,
        double latitudeDeg,
        double longitudeDeg,
        double elevationM,
        String timezone,
        String horizonMaskJson) {}
