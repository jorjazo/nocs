package dev.nocs.target.catalog;

import dev.nocs.target.Target;
import dev.nocs.target.TargetKind;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

public final class CatalogLoader {

    private CatalogLoader() {}

    public static List<Target> loadFromClasspath(ClassLoader cl, List<String> resourceNames) throws IOException {
        List<Target> out = new ArrayList<>();
        for (String name : resourceNames) {
            try (InputStream in = cl.getResourceAsStream(name)) {
                if (in == null) throw new IOException("catalog resource not found: " + name);
                out.addAll(readTsv(in));
            }
        }
        return out;
    }

    public static List<Target> readTsv(InputStream in) throws IOException {
        List<Target> targets = new ArrayList<>();
        try (BufferedReader br = new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8))) {
            String line;
            while ((line = br.readLine()) != null) {
                if (line.isBlank() || line.startsWith("#")) continue;
                String[] cols = line.split("\t", -1);
                if (cols.length < 10) continue;
                try {
                    List<String> aliases = cols[2].isBlank()
                            ? List.of()
                            : Arrays.stream(cols[2].split(","))
                                    .map(String::trim)
                                    .filter(s -> !s.isEmpty())
                                    .toList();
                    double ra = parseDoubleOrNaN(cols[4]);
                    double dec = parseDoubleOrNaN(cols[5]);
                    double mag = parseDoubleOrNaN(cols[7]);
                    double size = parseSize(cols[8]);
                    targets.add(new Target(
                            cols[0],
                            cols[1],
                            aliases,
                            TargetKind.parseOrOther(cols[3]),
                            ra,
                            dec,
                            cols[6],
                            mag,
                            size,
                            cols.length > 9 ? cols[9] : ""));
                } catch (RuntimeException rex) {
                    // Skip malformed rows; bundled TSVs should not have any, but be lenient.
                }
            }
        }
        return targets;
    }

    private static double parseDoubleOrNaN(String s) {
        if (s == null || s.isBlank() || "NaN".equalsIgnoreCase(s.trim())) return Double.NaN;
        try {
            return Double.parseDouble(s.trim());
        } catch (NumberFormatException e) {
            return Double.NaN;
        }
    }

    private static double parseSize(String s) {
        if (s == null || s.isBlank() || "NaN".equalsIgnoreCase(s.trim())) return Double.NaN;
        // Accept "189.1x61.7" style (major dim) — take the larger; otherwise parse as number.
        String v = s.trim().toLowerCase();
        int x = v.indexOf('x');
        String chosen = x > 0 ? v.substring(0, x) : v;
        return parseDoubleOrNaN(chosen);
    }
}
