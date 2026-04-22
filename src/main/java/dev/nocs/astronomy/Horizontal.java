package dev.nocs.astronomy;

import java.time.Instant;

public final class Horizontal {

    private Horizontal() {}

    /**
     * Apparent equatorial (RA/Dec, degrees, equator-of-date) → horizontal (alt, az degrees).
     * Az is measured east of north (0 = north, 90 = east).
     *
     * @param applyRefraction when true, the returned altitude is apparent (atmospheric-refraction-raised).
     */
    public static double[] equatorialToHorizontal(
            double raDeg, double decDeg, GeographicLocation loc, Instant utc, boolean applyRefraction) {
        double lst = Time.lstDeg(utc, loc.longitudeDeg());
        double ha = Math.toRadians(Angles.normalizePM180(lst - raDeg));
        double dec = Math.toRadians(decDeg);
        double lat = Math.toRadians(loc.latitudeDeg());

        double sinAlt = Math.sin(lat) * Math.sin(dec) + Math.cos(lat) * Math.cos(dec) * Math.cos(ha);
        double alt = Math.asin(clamp(sinAlt, -1.0, 1.0));
        double cosAz = (Math.sin(dec) - Math.sin(alt) * Math.sin(lat)) / (Math.cos(alt) * Math.cos(lat));
        double az = Math.acos(clamp(cosAz, -1.0, 1.0));
        if (Math.sin(ha) > 0) az = 2 * Math.PI - az;

        double altDeg = Math.toDegrees(alt);
        double azDeg = Angles.normalize360(Math.toDegrees(az));
        if (applyRefraction) altDeg = applyRefraction(altDeg);
        return new double[] {altDeg, azDeg};
    }

    /** Bennett (1982) apparent altitude from true altitude (degrees). */
    public static double applyRefraction(double altitudeDeg) {
        if (altitudeDeg < -1.0) return altitudeDeg;
        double arcmin = 1.0 / Math.tan(Math.toRadians(altitudeDeg + 7.31 / (altitudeDeg + 4.4)));
        return altitudeDeg + arcmin / 60.0;
    }

    /** Kasten-Young airmass approximation. */
    public static double airmass(double altitudeDeg) {
        if (altitudeDeg <= 0) return Double.POSITIVE_INFINITY;
        double z = 90.0 - altitudeDeg;
        double zRad = Math.toRadians(z);
        return 1.0 / (Math.cos(zRad) + 0.50572 * Math.pow(96.07995 - z, -1.6364));
    }

    private static double clamp(double v, double lo, double hi) {
        return Math.max(lo, Math.min(hi, v));
    }
}
