package dev.nocs.observatory.api.dto;

import dev.nocs.observatory.Observatory;

public record ObservatoryView(
        long id,
        String name,
        double latitudeDeg,
        double longitudeDeg,
        double elevationM,
        String timezone,
        String horizonMaskJson,
        boolean active) {

    public static ObservatoryView of(Observatory o) {
        return new ObservatoryView(
                o.id(),
                o.name(),
                o.latitudeDeg(),
                o.longitudeDeg(),
                o.elevationM(),
                o.timezone(),
                o.horizonMaskJson(),
                o.active());
    }
}
