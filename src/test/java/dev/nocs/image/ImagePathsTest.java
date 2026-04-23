package dev.nocs.image;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.assertj.core.api.Assertions.assertThat;

class ImagePathsTest {

    private final LocalDate date = LocalDate.of(2026, 4, 22);

    @Test
    void buildsCanonicalPath(@TempDir Path tempDir) {
        CaptureContext ctx = new CaptureContext("L", "M31", 120.0, "L_120s", 1);
        Path out = ImagePaths.forCapture(tempDir, date, "ccd-sim", ctx);

        assertThat(out).isEqualTo(
                tempDir.resolve("sessions").resolve("2026-04-22").resolve("m31")
                        .resolve("L_120s_001.fits"));
    }

    @Test
    void sanitisesTargetAndFilter(@TempDir Path tempDir) {
        CaptureContext ctx = new CaptureContext("Ha 7nm", "NGC 7000", 300.0, "Ha_300s", 5);
        Path out = ImagePaths.forCapture(tempDir, date, "ccd-sim", ctx);

        assertThat(out.getParent().getFileName().toString()).isEqualTo("ngc-7000");
        assertThat(out.getFileName().toString()).isEqualTo("Ha7nm_300s_005.fits");
    }

    @Test
    void formatsExposureWithoutTrailingZeros(@TempDir Path tempDir) {
        CaptureContext ctx = new CaptureContext("L", "m31", 0.5, "L_0.5s", 1);
        Path out = ImagePaths.forCapture(tempDir, date, "ccd-sim", ctx);

        assertThat(out.getFileName().toString()).isEqualTo("L_0.5s_001.fits");
    }

    @Test
    void avoidsCollisionsByBumpingSeq(@TempDir Path tempDir) throws Exception {
        CaptureContext ctx = new CaptureContext("L", "m31", 120.0, "L_120s", 1);
        Path first = ImagePaths.forCapture(tempDir, date, "ccd-sim", ctx);
        Files.createDirectories(first.getParent());
        Files.writeString(first, "x");

        Path next = ImagePaths.nextAvailable(first);
        assertThat(next.getFileName().toString()).isEqualTo("L_120s_002.fits");
    }

    @Test
    void thumbnailSibling(@TempDir Path tempDir) {
        CaptureContext ctx = new CaptureContext("L", "m31", 120.0, "L_120s", 1);
        Path fits = ImagePaths.forCapture(tempDir, date, "ccd-sim", ctx);
        Path thumb = ImagePaths.thumbnailFor(fits);
        assertThat(thumb.getFileName().toString()).isEqualTo("L_120s_001.thumb.jpg");
    }
}
