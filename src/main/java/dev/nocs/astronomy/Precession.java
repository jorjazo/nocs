package dev.nocs.astronomy;

import java.time.Instant;

/**
 * IAU 1976 precession from J2000.0 to the equator-of-date. Accurate to ~1 arcsec
 * over ±100 years, which is more than the v0.1 budget.
 * Reference: Meeus, Astronomical Algorithms §21.
 */
public final class Precession {

    private Precession() {}

    public static double[] precessFromJ2000(double raDeg, double decDeg, Instant when) {
        double t = (Time.julianDay(when) - Time.JD_J2000) / 36525.0;
        if (t == 0.0) return new double[] {raDeg, decDeg};

        double arcsec = 1.0 / 3600.0;
        double zetaDeg = arcsec * (2306.2181 * t + 0.30188 * t * t + 0.017998 * t * t * t);
        double zDeg = arcsec * (2306.2181 * t + 1.09468 * t * t + 0.018203 * t * t * t);
        double thetaDeg = arcsec * (2004.3109 * t - 0.42665 * t * t - 0.041833 * t * t * t);

        double zeta = Math.toRadians(zetaDeg);
        double z = Math.toRadians(zDeg);
        double theta = Math.toRadians(thetaDeg);

        double ra0 = Math.toRadians(raDeg);
        double dec0 = Math.toRadians(decDeg);

        double A = Math.cos(dec0) * Math.sin(ra0 + zeta);
        double B = Math.cos(theta) * Math.cos(dec0) * Math.cos(ra0 + zeta) - Math.sin(theta) * Math.sin(dec0);
        double C = Math.sin(theta) * Math.cos(dec0) * Math.cos(ra0 + zeta) + Math.cos(theta) * Math.sin(dec0);

        double raNew = Math.atan2(A, B) + z;
        double decNew = Math.asin(C);

        return new double[] {
            Angles.normalize360(Math.toDegrees(raNew)),
            Math.toDegrees(decNew)
        };
    }
}
