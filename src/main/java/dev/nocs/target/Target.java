package dev.nocs.target;

import java.util.List;

/**
 * Immutable target record. raJ2000Deg and decJ2000Deg may be NaN only for
 * solar-system bodies that compute position on demand; for those, callers use
 * {@link dev.nocs.target.catalog.SolarSystemCatalog} to resolve the live value.
 */
public record Target(
        String id,
        String primaryName,
        List<String> aliases,
        TargetKind kind,
        double raJ2000Deg,
        double decJ2000Deg,
        String constellation,
        double magnitude,
        double sizeArcmin,
        String notes) {

    public boolean hasFixedCoordinates() {
        return !Double.isNaN(raJ2000Deg) && !Double.isNaN(decJ2000Deg);
    }
}
