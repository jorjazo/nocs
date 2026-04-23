package dev.nocs.platesolving.domain;

import dev.nocs.platesolving.PlateSolution;
import java.time.Instant;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class PlateSolutionTest {

    @Test
    void wcsCardsContainCrvalAndScale() {
        Instant now = Instant.parse("2026-04-22T22:00:00Z");
        PlateSolution s = new PlateSolution(
                10.6847083, 41.269083, 1.234, 12.5, 0.5, 0.4, now, "astap");

        java.util.SequencedMap<String, String> cards = s.toFitsCards();

        assertThat(cards).containsEntry("CRVAL1", "10.6847083");
        assertThat(cards).containsEntry("CRVAL2", "41.269083");
        assertThat(cards).containsEntry("PLTSOLVD", "T");
        assertThat(cards).containsKey("CDELT1");
        assertThat(cards).containsKey("CROTA2");
        assertThat(cards.get("PLATESLV")).isEqualTo("'astap   '");
    }
}
