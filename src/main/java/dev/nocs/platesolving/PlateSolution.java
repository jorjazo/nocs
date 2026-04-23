package dev.nocs.platesolving;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.SequencedMap;

public record PlateSolution(
        double raJ2000Deg,
        double decJ2000Deg,
        double pixelScaleArcsecPerPx,
        double rotationDeg,
        double fieldWidthDeg,
        double fieldHeightDeg,
        Instant solvedAt,
        String solver) {

    public PlateSolution {
        if (raJ2000Deg < 0 || raJ2000Deg >= 360) {
            throw new IllegalArgumentException("raJ2000Deg must be in [0, 360), got " + raJ2000Deg);
        }
        if (decJ2000Deg < -90 || decJ2000Deg > 90) {
            throw new IllegalArgumentException("decJ2000Deg must be in [-90, 90], got " + decJ2000Deg);
        }
        if (solver == null || solver.isBlank()) {
            solver = "unknown";
        }
        if (solvedAt == null) {
            solvedAt = Instant.now();
        }
    }

    /**
     * FITS WCS-style header cards. Inserted into the saved FITS via
     * {@link dev.nocs.image.ImageStoreService#amendHeader(long, java.util.Map)}.
     * Insertion order is preserved by {@link SequencedMap}.
     */
    public SequencedMap<String, String> toFitsCards() {
        SequencedMap<String, String> cards = new LinkedHashMap<>();
        cards.put("PLTSOLVD", "T");
        cards.put("CTYPE1", "'RA---TAN'");
        cards.put("CTYPE2", "'DEC--TAN'");
        cards.put("CRVAL1", trim(raJ2000Deg));
        cards.put("CRVAL2", trim(decJ2000Deg));
        double cdelt = pixelScaleArcsecPerPx / 3600.0;
        cards.put("CDELT1", trim(-cdelt));
        cards.put("CDELT2", trim(cdelt));
        cards.put("CROTA1", trim(rotationDeg));
        cards.put("CROTA2", trim(rotationDeg));
        cards.put("PLATESLV", quote(solver));
        cards.put("PLTSOLDT", quote(solvedAt.toString()));
        cards.put("FOVWIDTH", trim(fieldWidthDeg));
        cards.put("FOVHIGHT", trim(fieldHeightDeg));
        return cards;
    }

    private static String trim(double v) {
        return String.format(Locale.ROOT, "%.10f", v).replaceAll("0+$", "").replaceAll("\\.$", ".0");
    }

    private static String quote(String s) {
        String trimmed = s.length() > 8 ? s.substring(0, 8) : s;
        return "'" + String.format(Locale.ROOT, "%-8s", trimmed) + "'";
    }
}
