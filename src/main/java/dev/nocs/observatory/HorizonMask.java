package dev.nocs.observatory;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;

public final class HorizonMask {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final List<Point> points;

    private HorizonMask(List<Point> points) {
        this.points = points;
    }

    public record Point(double azDeg, double altDeg) {}

    public static HorizonMask empty() {
        return new HorizonMask(List.of());
    }

    public static HorizonMask parse(String json) {
        try {
            List<Map<String, Number>> raw =
                    MAPPER.readValue(json, new TypeReference<List<Map<String, Number>>>() {});
            List<Point> pts = new ArrayList<>();
            for (Map<String, Number> m : raw) {
                Number az = m.get("az"), alt = m.get("alt");
                if (az == null || alt == null) {
                    throw new IllegalArgumentException("mask point needs 'az' and 'alt': " + m);
                }
                pts.add(new Point(normalize(az.doubleValue()), alt.doubleValue()));
            }
            pts.sort(Comparator.comparingDouble(Point::azDeg));
            return new HorizonMask(List.copyOf(pts));
        } catch (com.fasterxml.jackson.core.JsonProcessingException e) {
            throw new IllegalArgumentException("invalid horizon mask JSON: " + e.getMessage(), e);
        }
    }

    public double minAltitudeAt(double azDeg) {
        if (points.isEmpty()) return 0.0;
        if (points.size() == 1) return points.get(0).altDeg();
        double az = normalize(azDeg);
        Point prev = points.get(points.size() - 1);
        for (Point p : points) {
            double segStart = prev.azDeg();
            double segEnd = p.azDeg();
            double span = segEnd - segStart;
            if (span < 0) span += 360.0;
            double within = az - segStart;
            if (within < 0) within += 360.0;
            if (within <= span) {
                double t = span == 0 ? 0 : within / span;
                return prev.altDeg() + t * (p.altDeg() - prev.altDeg());
            }
            prev = p;
        }
        return points.get(0).altDeg();
    }

    public List<Point> points() {
        return points;
    }

    public String toJson() {
        try {
            List<Map<String, Object>> raw = points.stream()
                    .map(p -> (Map<String, Object>) Map.<String, Object>of("az", p.azDeg(), "alt", p.altDeg()))
                    .toList();
            return MAPPER.writeValueAsString(raw);
        } catch (com.fasterxml.jackson.core.JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
    }

    private static double normalize(double az) {
        double r = az % 360.0;
        if (r < 0) r += 360.0;
        return r;
    }
}
