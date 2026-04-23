package dev.nocs.platesolving.astap;

import dev.nocs.platesolving.FailureKind;
import dev.nocs.platesolving.PlateSolution;
import dev.nocs.platesolving.SolveOutcome;
import java.time.Instant;
import java.util.HashMap;
import java.util.Map;
import org.springframework.stereotype.Component;

@Component
public class AstapIniParser {

    public SolveOutcome parse(String iniText, long durationMs, Instant now) {
        if (iniText == null || iniText.isBlank()) {
            return new SolveOutcome.Failed(FailureKind.INTERNAL_ERROR, "empty ini output", durationMs);
        }
        Map<String, String> kv = parseKv(iniText);
        String solved = kv.get("PLTSOLVD");
        if (solved == null) {
            return new SolveOutcome.Failed(
                    FailureKind.INTERNAL_ERROR, "PLTSOLVD missing", durationMs);
        }
        if (!"T".equalsIgnoreCase(solved)) {
            String err = kv.getOrDefault("ERROR", "");
            FailureKind kind = err.toLowerCase().contains("star")
                    ? FailureKind.NO_STARS
                    : FailureKind.NO_STARS;
            return new SolveOutcome.Failed(kind, err.isBlank() ? "solver did not converge" : err, durationMs);
        }

        try {
            double crval1 = parseDouble(kv, "CRVAL1");
            double crval2 = parseDouble(kv, "CRVAL2");
            double cdelt1 = parseDouble(kv, "CDELT1");
            double cdelt2 = parseDouble(kv, "CDELT2");
            double crota = kv.containsKey("CROTA2")
                    ? parseDouble(kv, "CROTA2")
                    : kv.containsKey("CROTA1") ? parseDouble(kv, "CROTA1") : 0.0;
            int naxis1 = (int) Math.round(parseDouble(kv, "NAXIS1"));
            int naxis2 = (int) Math.round(parseDouble(kv, "NAXIS2"));

            double pixelScale = Math.abs(cdelt2) * 3600.0;
            double fieldWidth = Math.abs(cdelt1) * naxis1;
            double fieldHeight = Math.abs(cdelt2) * naxis2;
            double ra = ((crval1 % 360.0) + 360.0) % 360.0;

            PlateSolution s = new PlateSolution(
                    ra, crval2, pixelScale, crota, fieldWidth, fieldHeight, now, "astap");
            return new SolveOutcome.Solved(s, durationMs);
        } catch (RuntimeException e) {
            return new SolveOutcome.Failed(
                    FailureKind.INTERNAL_ERROR, "ini parse failed: " + e.getMessage(), durationMs);
        }
    }

    private static Map<String, String> parseKv(String text) {
        Map<String, String> out = new HashMap<>();
        for (String line : text.split("\\r?\\n")) {
            int eq = line.indexOf('=');
            if (eq <= 0) {
                continue;
            }
            String k = line.substring(0, eq).trim();
            String v = line.substring(eq + 1).trim();
            if (!k.isEmpty()) {
                out.put(k, v);
            }
        }
        return out;
    }

    private static double parseDouble(Map<String, String> kv, String key) {
        String v = kv.get(key);
        if (v == null || v.isBlank()) {
            throw new IllegalArgumentException("missing " + key);
        }
        return Double.parseDouble(v);
    }
}
