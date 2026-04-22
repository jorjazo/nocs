package dev.nocs.observatory;

import dev.nocs.astronomy.GeographicLocation;

public record Observatory(
        long id,
        String name,
        double latitudeDeg,
        double longitudeDeg,
        double elevationM,
        String timezone,
        String horizonMaskJson,
        boolean active) {

    public GeographicLocation location() {
        return new GeographicLocation(latitudeDeg, longitudeDeg, elevationM);
    }

    public HorizonMask horizonMask() {
        return HorizonMask.parse(horizonMaskJson);
    }
}
