package dev.nocs.image;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;

public final class ImagePaths {

    private static final DateTimeFormatter DATE = DateTimeFormatter.ISO_LOCAL_DATE;

    private ImagePaths() {}

    public static Path forCapture(Path dataDir, LocalDate date, String deviceId, CaptureContext ctx) {
        String filter = sanitiseFilter(ctx.filter());
        String target = sanitiseTarget(ctx.target());
        String exposure = formatExposure(ctx.exposureSec());
        int seq = ctx.seq() <= 0 ? 1 : ctx.seq();
        String filename = filter + "_" + exposure + "s_" + zeroPad(seq) + ".fits";
        return dataDir.resolve("sessions").resolve(DATE.format(date)).resolve(target).resolve(filename);
    }

    public static Path nextAvailable(Path candidate) {
        if (!Files.exists(candidate)) {
            return candidate;
        }
        Path parent = candidate.getParent();
        String name = candidate.getFileName().toString();
        int dot = name.lastIndexOf('.');
        int underscore = name.lastIndexOf('_', dot);
        if (dot < 0 || underscore < 0) {
            return candidate;
        }
        String prefix = name.substring(0, underscore);
        String suffix = name.substring(dot);
        int seq;
        try {
            seq = Integer.parseInt(name.substring(underscore + 1, dot));
        } catch (NumberFormatException e) {
            return candidate;
        }
        Path next;
        do {
            seq++;
            next = parent.resolve(prefix + "_" + zeroPad(seq) + suffix);
        } while (Files.exists(next) && seq < 99_999);
        return next;
    }

    public static Path thumbnailFor(Path fits) {
        String name = fits.getFileName().toString();
        int dot = name.lastIndexOf('.');
        String stem = dot < 0 ? name : name.substring(0, dot);
        return fits.resolveSibling(stem + ".thumb.jpg");
    }

    static String sanitiseTarget(String s) {
        String trimmed = s.trim().toLowerCase();
        String slug = trimmed.replaceAll("[^a-z0-9]+", "-").replaceAll("^-|-$", "");
        return slug.isEmpty() ? "untargeted" : slug;
    }

    static String sanitiseFilter(String s) {
        String trimmed = s.trim();
        String safe = trimmed.replaceAll("[^A-Za-z0-9]", "");
        return safe.isEmpty() ? "UNK" : safe;
    }

    static String formatExposure(double seconds) {
        if (seconds == Math.floor(seconds) && !Double.isInfinite(seconds)) {
            return Long.toString((long) seconds);
        }
        String s = String.format(java.util.Locale.ROOT, "%.3f", seconds);
        s = s.replaceAll("0+$", "").replaceAll("\\.$", "");
        return s;
    }

    static String zeroPad(int seq) {
        if (seq < 1000) {
            return String.format(java.util.Locale.ROOT, "%03d", seq);
        }
        return Integer.toString(seq);
    }
}
