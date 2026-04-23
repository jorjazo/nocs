package dev.nocs.platesolving.domain;

import dev.nocs.platesolving.FailureKind;
import dev.nocs.platesolving.PlateSolution;
import dev.nocs.platesolving.SolveOutcome;
import java.time.Instant;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SolveOutcomeTest {

    @Test
    void solvedExposesSolution() {
        PlateSolution s = new PlateSolution(1, 2, 3, 0, 0, 0, Instant.EPOCH, "astap");
        SolveOutcome.Solved out = new SolveOutcome.Solved(s, 1234L);
        assertThat(out.solution()).isSameAs(s);
        assertThat(out.durationMs()).isEqualTo(1234L);
    }

    @Test
    void failureKindIsCarried() {
        SolveOutcome.Failed f = new SolveOutcome.Failed(FailureKind.NO_STARS, "too few", 200L);
        assertThat(f.kind()).isEqualTo(FailureKind.NO_STARS);
        assertThat(f.message()).isEqualTo("too few");
        assertThat(f.durationMs()).isEqualTo(200L);
    }
}
