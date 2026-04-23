package dev.nocs.platesolving.astap;

import dev.nocs.platesolving.FailureKind;
import dev.nocs.platesolving.PlateSolution;
import dev.nocs.platesolving.SolveOutcome;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.ClassPathResource;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

class AstapIniParserTest {

    @Test
    void parsesSolvedIni() throws Exception {
        String text = read("platesolving/astap/fake-astap-solved.ini");

        SolveOutcome out = new AstapIniParser().parse(text, 1234L, Instant.parse("2026-04-22T22:00:00Z"));

        assertThat(out).isInstanceOf(SolveOutcome.Solved.class);
        SolveOutcome.Solved solved = (SolveOutcome.Solved) out;
        PlateSolution s = solved.solution();
        assertThat(s.raJ2000Deg()).isCloseTo(10.6847083, within(1e-9));
        assertThat(s.decJ2000Deg()).isEqualTo(41.269083);
        assertThat(s.pixelScaleArcsecPerPx()).isCloseTo(0.000342222 * 3600.0, within(1e-6));
        assertThat(s.rotationDeg()).isEqualTo(12.5);
        assertThat(s.fieldWidthDeg()).isCloseTo(0.000342222 * 1024.0, within(1e-6));
        assertThat(s.fieldHeightDeg()).isCloseTo(0.000342222 * 768.0, within(1e-6));
        assertThat(s.solver()).isEqualTo("astap");
        assertThat(solved.durationMs()).isEqualTo(1234L);
    }

    @Test
    void parsesFailedIni() throws Exception {
        String text = read("platesolving/astap/fake-astap-failed.ini");

        SolveOutcome out = new AstapIniParser().parse(text, 200L, Instant.now());

        assertThat(out).isInstanceOf(SolveOutcome.Failed.class);
        SolveOutcome.Failed f = (SolveOutcome.Failed) out;
        assertThat(f.kind()).isEqualTo(FailureKind.NO_STARS);
        assertThat(f.message()).contains("Less than 30 stars");
        assertThat(f.durationMs()).isEqualTo(200L);
    }

    @Test
    void emptyTextIsInternalError() {
        SolveOutcome out = new AstapIniParser().parse("", 0L, Instant.now());

        assertThat(out).isInstanceOf(SolveOutcome.Failed.class);
        assertThat(((SolveOutcome.Failed) out).kind()).isEqualTo(FailureKind.INTERNAL_ERROR);
    }

    @Test
    void missingPltSolvdIsInternalError() {
        SolveOutcome out = new AstapIniParser().parse("CRVAL1=10\nCRVAL2=41\n", 0L, Instant.now());
        assertThat(((SolveOutcome.Failed) out).kind()).isEqualTo(FailureKind.INTERNAL_ERROR);
    }

    private static String read(String classpath) throws Exception {
        try (var in = new ClassPathResource(classpath).getInputStream()) {
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        }
    }
}
