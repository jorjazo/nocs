package dev.nocs.image;

import java.awt.image.BufferedImage;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class FitsStretcherTest {

    @Test
    void stretchesBitpix16IntoGrayBufferedImage() {
        short[] pixels = new short[16];
        for (int i = 0; i < 16; i++) {
            int raw = i < 8 ? 100 : 60000;
            pixels[i] = (short) (raw - 32768);
        }
        byte[] fits = MiniFits.build16(4, 4, pixels, null);
        FitsHeaderReader.Header h = FitsHeaderReader.read(fits);

        BufferedImage img = FitsStretcher.stretch(h, fits, 32);
        assertThat(img.getWidth()).isEqualTo(4);
        assertThat(img.getHeight()).isEqualTo(4);
        var r = img.getRaster();
        int min = 255;
        int max = 0;
        for (int y = 0; y < 4; y++) {
            for (int x = 0; x < 4; x++) {
                int v = r.getSample(x, y, 0);
                min = Math.min(min, v);
                max = Math.max(max, v);
            }
        }
        assertThat(max).isGreaterThan(min + 50);
    }

    @Test
    void downscalesWhenLargerThanMaxDim() {
        short[] pixels = new short[64 * 64];
        byte[] fits = MiniFits.build16(64, 64, pixels, null);
        FitsHeaderReader.Header h = FitsHeaderReader.read(fits);

        BufferedImage img = FitsStretcher.stretch(h, fits, 32);
        assertThat(img.getWidth()).isLessThanOrEqualTo(32);
        assertThat(img.getHeight()).isLessThanOrEqualTo(32);
    }

    @Test
    void rejectsUnsupportedBitpix() {
        org.junit.jupiter.api.Assertions.assertThrows(
                IllegalArgumentException.class,
                () -> FitsStretcher.stretch(
                        new FitsHeaderReader.Header(8, 2, 4, 4, 0, 1, null, 2880),
                        new byte[2880 + 16],
                        32));
    }
}
