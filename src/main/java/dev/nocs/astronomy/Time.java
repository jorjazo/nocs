package dev.nocs.astronomy;

import java.time.Instant;

public final class Time {

    public static final double JD_J2000 = 2451545.0;
    public static final double DAY_SECONDS = 86400.0;

    private Time() {}

    /** Julian Day at the given UTC instant. */
    public static double julianDay(Instant utc) {
        return 2440587.5 + utc.toEpochMilli() / 1000.0 / DAY_SECONDS;
    }

    /** Days since J2000.0 (TT = UT for this plan's precision). */
    public static double daysSinceJ2000(Instant utc) {
        return julianDay(utc) - JD_J2000;
    }

    /** Greenwich Mean Sidereal Time in degrees, 0..360. Meeus (12.4). */
    public static double gmstDeg(Instant utc) {
        double jd = julianDay(utc);
        double t = (jd - JD_J2000) / 36525.0;
        double gmst = 280.46061837
                + 360.98564736629 * (jd - JD_J2000)
                + 0.000387933 * t * t
                - (t * t * t) / 38710000.0;
        return Angles.normalize360(gmst);
    }

    /** Local Sidereal Time in degrees at the given east-positive longitude. */
    public static double lstDeg(Instant utc, double longitudeDeg) {
        return Angles.normalize360(gmstDeg(utc) + longitudeDeg);
    }
}
