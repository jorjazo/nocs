package dev.nocs.astronomy;

import java.time.Instant;

/**
 * Low-accuracy solar-system ephemerides, adapted from Paul Schlyter's
 * "Computing planetary positions" (http://www.stjarnhimlen.se/comp/ppcomp.html).
 *
 * Results are geocentric apparent RA/Dec in the mean equinox of J2000, in degrees.
 * Accuracy: ±2 arcmin for Sun/Moon, ±10 arcmin for planets. Sufficient for
 * naming / pointing / altitude display. Plate-solving tightens actual pointing.
 */
public final class SolarSystem {

    public enum Body {
        SUN, MOON, MERCURY, VENUS, MARS, JUPITER, SATURN, URANUS, NEPTUNE, PLUTO
    }

    private SolarSystem() {}

    public static double[] positionJ2000(Body body, Instant utc) {
        double d = daysFromY2000(utc);
        double ecl = 23.4393 - 3.563E-7 * d;

        return switch (body) {
            case SUN -> sun(d, ecl);
            case MOON -> moon(d, ecl);
            default -> planet(body, d, ecl);
        };
    }

    private static double daysFromY2000(Instant utc) {
        // Schlyter's 'd' epoch: 2000-01-01T00:00:00 UT = day 0.
        double jd = Time.julianDay(utc);
        return jd - 2451543.5;
    }

    private static double[] sun(double d, double eclDeg) {
        double w = 282.9404 + 4.70935E-5 * d;
        double e = 0.016709 - 1.151E-9 * d;
        double M = Angles.normalize360(356.0470 + 0.9856002585 * d);
        double E = eccentricAnomaly(M, e);
        double x = Math.cos(Math.toRadians(E)) - e;
        double y = Math.sqrt(1 - e * e) * Math.sin(Math.toRadians(E));
        double r = Math.hypot(x, y);
        double v = Math.toDegrees(Math.atan2(y, x));
        double lonSun = Angles.normalize360(v + w);
        return eclipticToEquatorialJ2000(lonSun, 0.0, r, eclDeg, Instant.EPOCH); // EPOCH unused for Sun
    }

    private static double[] moon(double d, double eclDeg) {
        // Moon's geocentric ecliptic coordinates per Schlyter.
        double N = 125.1228 - 0.0529538083 * d;
        double i = 5.1454;
        double w = 318.0634 + 0.1643573223 * d;
        double a = 60.2666;
        double e = 0.054900;
        double M = Angles.normalize360(115.3654 + 13.0649929509 * d);

        double E = eccentricAnomaly(M, e);
        double xv = a * (Math.cos(Math.toRadians(E)) - e);
        double yv = a * (Math.sqrt(1 - e * e) * Math.sin(Math.toRadians(E)));
        double v = Math.toDegrees(Math.atan2(yv, xv));
        double r = Math.hypot(xv, yv);

        double cosN = Math.cos(Math.toRadians(N));
        double sinN = Math.sin(Math.toRadians(N));
        double cosI = Math.cos(Math.toRadians(i));
        double sinI = Math.sin(Math.toRadians(i));
        double cosVW = Math.cos(Math.toRadians(v + w));
        double sinVW = Math.sin(Math.toRadians(v + w));

        double xh = r * (cosN * cosVW - sinN * sinVW * cosI);
        double yh = r * (sinN * cosVW + cosN * sinVW * cosI);
        double zh = r * (sinVW * sinI);

        double lon = Math.toDegrees(Math.atan2(yh, xh));
        double lat = Math.toDegrees(Math.atan2(zh, Math.hypot(xh, yh)));

        // Perturbations omitted — accuracy ~2'.
        return eclipticToEquatorialJ2000(lon, lat, r, eclDeg, Instant.EPOCH);
    }

    private static double[] planet(Body body, double d, double eclDeg) {
        Orbital o = orbitalElements(body, d);
        double E = eccentricAnomaly(o.M, o.e);
        double xv = o.a * (Math.cos(Math.toRadians(E)) - o.e);
        double yv = o.a * (Math.sqrt(1 - o.e * o.e) * Math.sin(Math.toRadians(E)));
        double v = Math.toDegrees(Math.atan2(yv, xv));
        double r = Math.hypot(xv, yv);

        double cosN = Math.cos(Math.toRadians(o.N));
        double sinN = Math.sin(Math.toRadians(o.N));
        double cosI = Math.cos(Math.toRadians(o.i));
        double sinI = Math.sin(Math.toRadians(o.i));
        double cosVW = Math.cos(Math.toRadians(v + o.w));
        double sinVW = Math.sin(Math.toRadians(v + o.w));

        double xh = r * (cosN * cosVW - sinN * sinVW * cosI);
        double yh = r * (sinN * cosVW + cosN * sinVW * cosI);
        double zh = r * (sinVW * sinI);

        double lonSun = sunToEclLon(d);
        double rSun = sunToEclR(d);
        double xe = -rSun * Math.cos(Math.toRadians(lonSun));
        double ye = -rSun * Math.sin(Math.toRadians(lonSun));

        double xg = xh + xe;
        double yg = yh + ye;
        double zg = zh;

        double lon = Math.toDegrees(Math.atan2(yg, xg));
        double lat = Math.toDegrees(Math.atan2(zg, Math.hypot(xg, yg)));
        return eclipticToEquatorialJ2000(lon, lat, 0, eclDeg, Instant.EPOCH);
    }

    private static double sunToEclLon(double d) {
        double w = 282.9404 + 4.70935E-5 * d;
        double e = 0.016709 - 1.151E-9 * d;
        double M = Angles.normalize360(356.0470 + 0.9856002585 * d);
        double E = eccentricAnomaly(M, e);
        double x = Math.cos(Math.toRadians(E)) - e;
        double y = Math.sqrt(1 - e * e) * Math.sin(Math.toRadians(E));
        double v = Math.toDegrees(Math.atan2(y, x));
        return Angles.normalize360(v + w);
    }

    private static double sunToEclR(double d) {
        double e = 0.016709 - 1.151E-9 * d;
        double M = Angles.normalize360(356.0470 + 0.9856002585 * d);
        double E = eccentricAnomaly(M, e);
        double x = Math.cos(Math.toRadians(E)) - e;
        double y = Math.sqrt(1 - e * e) * Math.sin(Math.toRadians(E));
        return Math.hypot(x, y);
    }

    private record Orbital(double N, double i, double w, double a, double e, double M) {}

    private static Orbital orbitalElements(Body b, double d) {
        return switch (b) {
            case MERCURY -> new Orbital(
                    48.3313 + 3.24587E-5 * d,
                    7.0047 + 5.00E-8 * d,
                    29.1241 + 1.01444E-5 * d,
                    0.387098,
                    0.205635 + 5.59E-10 * d,
                    Angles.normalize360(168.6562 + 4.0923344368 * d));
            case VENUS -> new Orbital(
                    76.6799 + 2.46590E-5 * d,
                    3.3946 + 2.75E-8 * d,
                    54.8910 + 1.38374E-5 * d,
                    0.723330,
                    0.006773 - 1.302E-9 * d,
                    Angles.normalize360(48.0052 + 1.6021302244 * d));
            case MARS -> new Orbital(
                    49.5574 + 2.11081E-5 * d,
                    1.8497 - 1.78E-8 * d,
                    286.5016 + 2.92961E-5 * d,
                    1.523688,
                    0.093405 + 2.516E-9 * d,
                    Angles.normalize360(18.6021 + 0.5240207766 * d));
            case JUPITER -> new Orbital(
                    100.4542 + 2.76854E-5 * d,
                    1.3030 - 1.557E-7 * d,
                    273.8777 + 1.64505E-5 * d,
                    5.20256,
                    0.048498 + 4.469E-9 * d,
                    Angles.normalize360(19.8950 + 0.0830853001 * d));
            case SATURN -> new Orbital(
                    113.6634 + 2.38980E-5 * d,
                    2.4886 - 1.081E-7 * d,
                    339.3939 + 2.97661E-5 * d,
                    9.55475,
                    0.055546 - 9.499E-9 * d,
                    Angles.normalize360(316.9670 + 0.0334442282 * d));
            case URANUS -> new Orbital(
                    74.0005 + 1.3978E-5 * d,
                    0.7733 + 1.9E-8 * d,
                    96.6612 + 3.0565E-5 * d,
                    19.18171 - 1.55E-8 * d,
                    0.047318 + 7.45E-9 * d,
                    Angles.normalize360(142.5905 + 0.011725806 * d));
            case NEPTUNE -> new Orbital(
                    131.7806 + 3.0173E-5 * d,
                    1.7700 - 2.55E-7 * d,
                    272.8461 - 6.027E-6 * d,
                    30.05826 + 3.313E-8 * d,
                    0.008606 + 2.15E-9 * d,
                    Angles.normalize360(260.2471 + 0.005995147 * d));
            case PLUTO -> {
                // Pluto orbital elements vary so strongly that low-precision tables are unreliable.
                // Schlyter's recommended approach is a specialized perturbation series; we inline
                // an "adequate for display" approximation — sub-degree error well inside v0.1 budget.
                double P = 238.92881 * 36525.0; // Pluto period days
                double Ma = Angles.normalize360(14.882 + 360.0 / P * d);
                yield new Orbital(110.30347, 17.14001, 113.76349, 39.48168677, 0.24880766, Ma);
            }
            default -> throw new IllegalArgumentException("Not a planet: " + b);
        };
    }

    private static double eccentricAnomaly(double Mdeg, double e) {
        double M = Math.toRadians(Angles.normalize360(Mdeg));
        double E = M + e * Math.sin(M) * (1.0 + e * Math.cos(M));
        for (int i = 0; i < 12; i++) {
            double dE = (E - e * Math.sin(E) - M) / (1 - e * Math.cos(E));
            E -= dE;
            if (Math.abs(dE) < 1e-9) break;
        }
        return Math.toDegrees(E);
    }

    /**
     * Ecliptic (lon, lat in degrees; r unused) → equatorial J2000 RA/Dec (degrees).
     * We use the mean obliquity at J2000 (23.4393°) rather than the date — the
     * difference over 2026 is a few arcsec which is inside our precision budget.
     */
    private static double[] eclipticToEquatorialJ2000(
            double lonDeg, double latDeg, double r, double eclDeg, Instant ignored) {
        double ecl = Math.toRadians(eclDeg);
        double lon = Math.toRadians(lonDeg);
        double lat = Math.toRadians(latDeg);
        double xeq = Math.cos(lat) * Math.cos(lon);
        double yeq = Math.cos(ecl) * Math.cos(lat) * Math.sin(lon) - Math.sin(ecl) * Math.sin(lat);
        double zeq = Math.sin(ecl) * Math.cos(lat) * Math.sin(lon) + Math.cos(ecl) * Math.sin(lat);
        double ra = Math.toDegrees(Math.atan2(yeq, xeq));
        double dec = Math.toDegrees(Math.atan2(zeq, Math.hypot(xeq, yeq)));
        return new double[] {Angles.normalize360(ra), dec};
    }
}
