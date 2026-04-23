package dev.nocs.image;

import java.util.Map;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class FitsHeaderReaderTest {

    @Test
    void parsesBitpix16Header() {
        byte[] fits = MiniFits.build16(4, 3, new short[12], Map.of(
                "DATE-OBS", "'2026-04-22T22:00:00'"));

        FitsHeaderReader.Header h = FitsHeaderReader.read(fits);

        assertThat(h.bitpix()).isEqualTo(16);
        assertThat(h.naxis()).isEqualTo(2);
        assertThat(h.naxis1()).isEqualTo(4);
        assertThat(h.naxis2()).isEqualTo(3);
        assertThat(h.bzero()).isEqualTo(32768.0);
        assertThat(h.bscale()).isEqualTo(1.0);
        assertThat(h.dateObs()).isEqualTo("2026-04-22T22:00:00");
        assertThat(h.dataOffset()).isEqualTo(2880);
    }

    @Test
    void parsesFloatHeader() {
        byte[] fits = MiniFits.buildFloat(2, 2, new float[]{0, 0, 0, 0}, null);

        FitsHeaderReader.Header h = FitsHeaderReader.read(fits);

        assertThat(h.bitpix()).isEqualTo(-32);
        assertThat(h.bzero()).isEqualTo(0.0);
        assertThat(h.bscale()).isEqualTo(1.0);
    }

    @Test
    void rejectsTrucated() {
        org.junit.jupiter.api.Assertions.assertThrows(
                IllegalArgumentException.class,
                () -> FitsHeaderReader.read(new byte[100]));
    }
}
