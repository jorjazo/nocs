package dev.nocs.platesolving.astap;

import dev.nocs.platesolving.FailureKind;
import dev.nocs.platesolving.SolveOptions;
import dev.nocs.platesolving.SolveOutcome;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.DisabledOnOs;
import org.junit.jupiter.api.condition.OS;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.core.io.ClassPathResource;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

@DisabledOnOs(OS.WINDOWS)
class AstapInvokerTest {

    @TempDir Path tmp;
    Path script;
    AstapInvoker invoker;

    @BeforeEach
    void setUp() throws IOException {
        script = tmp.resolve("fake-astap.sh");
        try (InputStream in = new ClassPathResource("platesolving/astap/fake-astap.sh").getInputStream()) {
            Files.copy(in, script, StandardCopyOption.REPLACE_EXISTING);
        }
        script.toFile().setExecutable(true);
        invoker = new AstapInvoker(new DefaultProcessRunner(), new AstapIniParser());
    }

    @Test
    void successPathReturnsSolved() {
        AstapInstallation inst = new AstapInstallation(script, tmp, "H18");

        SolveOutcome out = invoker.invoke(
                inst, fakeFits(), SolveOptions.defaults(), 30L, Map.of("FAKE_ASTAP_OUTCOME", "solved"));

        assertThat(out).isInstanceOf(SolveOutcome.Solved.class);
        assertThat(((SolveOutcome.Solved) out).solution().raJ2000Deg()).isCloseTo(10.6847083, within(1e-9));
    }

    @Test
    void failedScriptYieldsFailedOutcome() {
        AstapInstallation inst = new AstapInstallation(script, tmp, "H18");

        SolveOutcome out = invoker.invoke(
                inst, fakeFits(), SolveOptions.defaults(), 30L, Map.of("FAKE_ASTAP_OUTCOME", "failed"));

        assertThat(out).isInstanceOf(SolveOutcome.Failed.class);
        assertThat(((SolveOutcome.Failed) out).kind()).isEqualTo(FailureKind.NO_STARS);
    }

    @Test
    void timeoutYieldsTimeoutFailure() {
        AstapInstallation inst = new AstapInstallation(script, tmp, "H18");

        SolveOutcome out = invoker.invoke(
                inst, fakeFits(), SolveOptions.defaults(), 1L, Map.of("FAKE_ASTAP_SLEEP", "5"));

        assertThat(out).isInstanceOf(SolveOutcome.Failed.class);
        assertThat(((SolveOutcome.Failed) out).kind()).isEqualTo(FailureKind.TIMEOUT);
    }

    private static byte[] fakeFits() {
        return new byte[2880];
    }
}
