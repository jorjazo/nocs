package dev.nocs.image;

import java.io.ByteArrayInputStream;
import java.util.Map;
import java.util.Optional;
import javax.imageio.ImageIO;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class ThumbnailGeneratorTest {

    @Test
    void producesJpegFromBitpix16Fits() throws Exception {
        short[] pixels = new short[64 * 48];
        for (int i = 0; i < pixels.length; i++) {
            pixels[i] = (short) ((i * 37) % 32767);
        }
        byte[] fits = MiniFits.build16(64, 48, pixels, Map.of(
                "DATE-OBS", "'2026-04-22T22:00:00'"));

        ThumbnailGenerator gen = new ThumbnailGenerator();
        Optional<byte[]> jpeg = gen.generate(fits);

        assertThat(jpeg).isPresent();
        var img = ImageIO.read(new ByteArrayInputStream(jpeg.get()));
        assertThat(img).isNotNull();
        assertThat(img.getWidth()).isLessThanOrEqualTo(512);
        assertThat(img.getHeight()).isLessThanOrEqualTo(512);
    }

    @Test
    void returnsEmptyWhenUnsupportedBitpix() {
        byte[] block = new byte[2880];
        java.util.Arrays.fill(block, (byte) ' ');
        write(block, 0, "SIMPLE  =                    T");
        write(block, 80, "BITPIX  =                    8");
        write(block, 160, "NAXIS   =                    2");
        write(block, 240, "NAXIS1  =                    4");
        write(block, 320, "NAXIS2  =                    4");
        write(block, 400, "END");

        ThumbnailGenerator gen = new ThumbnailGenerator();
        Optional<byte[]> jpeg = gen.generate(block);

        assertThat(jpeg).isEmpty();
    }

    private static void write(byte[] target, int offset, String s) {
        byte[] bytes = s.getBytes();
        System.arraycopy(bytes, 0, target, offset, Math.min(bytes.length, 80));
    }
}
