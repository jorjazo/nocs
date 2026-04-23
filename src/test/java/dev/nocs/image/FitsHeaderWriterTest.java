package dev.nocs.image;

import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.SequencedMap;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class FitsHeaderWriterTest {

    @Test
    void appendsNewCardsAndKeepsDataIntact() {
        byte[] original = MiniFits.build16(8, 8, new short[64], java.util.Map.of(
                "DATE-OBS", "'2026-04-22T22:00:00'"));

        SequencedMap<String, String> additions = new LinkedHashMap<>();
        additions.put("CRVAL1", "10.6847083");
        additions.put("CRVAL2", "41.269083");
        additions.put("PLTSOLVD", "T");

        byte[] amended = FitsHeaderWriter.writeWithCards(original, additions);

        FitsHeaderReader.Header h = FitsHeaderReader.read(amended);
        assertThat(h.bitpix()).isEqualTo(16);
        assertThat(h.naxis()).isEqualTo(2);
        assertThat(h.naxis1()).isEqualTo(8);
        assertThat(h.naxis2()).isEqualTo(8);
        assertThat(amended.length % 2880).isZero();

        String headerText = new String(amended, 0, h.dataOffset(), StandardCharsets.US_ASCII);
        assertThat(headerText).contains("CRVAL1");
        assertThat(headerText).contains("CRVAL2");
        assertThat(headerText).contains("PLTSOLVD=                    T");

        FitsHeaderReader.Header ho = FitsHeaderReader.read(original);
        int dataLen = original.length - ho.dataOffset();
        assertThat(java.util.Arrays.copyOfRange(amended, h.dataOffset(), h.dataOffset() + dataLen))
                .isEqualTo(java.util.Arrays.copyOfRange(original, ho.dataOffset(), original.length));
    }

    @Test
    void replacesExistingCardInPlace() {
        byte[] original = MiniFits.build16(8, 8, new short[64], java.util.Map.of(
                "DATE-OBS", "'1999-01-01T00:00:00'"));

        SequencedMap<String, String> repl = new LinkedHashMap<>();
        repl.put("DATE-OBS", "'2026-04-22T22:00:00'");

        byte[] amended = FitsHeaderWriter.writeWithCards(original, repl);

        FitsHeaderReader.Header h = FitsHeaderReader.read(amended);
        assertThat(h.dateObs()).isEqualTo("2026-04-22T22:00:00");

        String headerText = new String(amended, 0, h.dataOffset(), StandardCharsets.US_ASCII);
        int idx = headerText.indexOf("DATE-OBS");
        assertThat(idx).isGreaterThan(-1);
        assertThat(headerText.indexOf("DATE-OBS", idx + 1)).isEqualTo(-1);
    }
}
