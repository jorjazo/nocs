package dev.nocs.astronomy;

public final class Angles {

    private Angles() {}

    public static double normalize360(double deg) {
        double r = deg % 360.0;
        if (r < 0) r += 360.0;
        return r;
    }

    public static double normalizePM180(double deg) {
        double r = normalize360(deg + 180.0) - 180.0;
        return r;
    }

    public static double degToRad(double deg) {
        return deg * Math.PI / 180.0;
    }

    public static double radToDeg(double rad) {
        return rad * 180.0 / Math.PI;
    }

    public static double parseHmsToDeg(String s) {
        double[] parts = splitThree(s);
        double hours = Math.abs(parts[0]) + parts[1] / 60.0 + parts[2] / 3600.0;
        double deg = hours * 15.0;
        return parts[0] < 0 ? -deg : deg;
    }

    public static double parseDmsToDeg(String s) {
        // Preserve sign on the first number (handle "-0" as negative too).
        boolean neg = s.trim().startsWith("-");
        double[] parts = splitThree(s);
        double mag = Math.abs(parts[0]) + parts[1] / 60.0 + parts[2] / 3600.0;
        if (neg || parts[0] < 0) mag = -mag;
        return mag;
    }

    private static double[] splitThree(String s) {
        String cleaned =
                s.replaceAll("[hHdD°]", " ")
                        .replaceAll("[mM'′]", " ")
                        .replaceAll("[sS\"″]", " ")
                        .replace(':', ' ')
                        .trim();
        String[] parts = cleaned.split("\\s+");
        if (parts.length < 3) {
            throw new IllegalArgumentException("expected 3 components in: " + s);
        }
        double a = Double.parseDouble(parts[0]);
        double b = Double.parseDouble(parts[1]);
        double c = Double.parseDouble(parts[2]);
        return new double[] {a, b, c};
    }
}
