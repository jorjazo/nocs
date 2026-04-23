package dev.nocs.platesolving.astap;

import dev.nocs.config.NocsProperties;
import dev.nocs.platesolving.FailureKind;
import dev.nocs.platesolving.PlateSolution;
import dev.nocs.platesolving.SolveOptions;
import dev.nocs.platesolving.SolveOutcome;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.assertj.core.api.Assertions.assertThat;

class AstapPlateSolverTest {

    @Test
    void notInstalledReturnsNotInstalled(@TempDir Path data) {
        AstapInstallationLocator locator = new AstapInstallationLocator();
        AstapInvoker invoker = new AstapInvoker(stubRunner(_r -> {
            throw new AssertionError("invoker should not run");
        }), new AstapIniParser());

        AstapPlateSolver solver = new AstapPlateSolver(locator, invoker, propsAstap(""), data);

        SolveOutcome out = solver.solve(new byte[100], SolveOptions.defaults());

        assertThat(out).isInstanceOf(SolveOutcome.Failed.class);
        assertThat(((SolveOutcome.Failed) out).kind()).isEqualTo(FailureKind.NOT_INSTALLED);
        assertThat(solver.isAvailable()).isFalse();
    }

    @Test
    void installedDelegatesToInvoker(@TempDir Path data) throws Exception {
        Path bin = Files.createDirectories(data.resolve("astap/bin")).resolve("astap_cli");
        Files.writeString(bin, "#!/bin/sh\nexit 0\n");
        bin.toFile().setExecutable(true);
        Files.createDirectories(data.resolve("astap/db"));
        Files.createFile(data.resolve("astap/db/h18_star_database_index.dat"));

        ProcessRunner runner = (cmd, work, env, t) -> {
            Path ini = work.resolve("input.ini");
            Files.writeString(
                    ini,
                    "PLTSOLVD=T\nCRVAL1=1.0\nCRVAL2=2.0\nCDELT1=-0.001\nCDELT2=0.001\n"
                            + "CROTA2=0\nNAXIS1=10\nNAXIS2=10\n");
            return new ProcessResult(0, "", "", false, 12L);
        };
        AstapInvoker invoker = new AstapInvoker(runner, new AstapIniParser());
        AstapPlateSolver solver = new AstapPlateSolver(
                new AstapInstallationLocator(), invoker, propsAstap(""), data);

        SolveOutcome out = solver.solve(new byte[2880], SolveOptions.defaults());

        assertThat(out).isInstanceOf(SolveOutcome.Solved.class);
        PlateSolution s = ((SolveOutcome.Solved) out).solution();
        assertThat(s.raJ2000Deg()).isEqualTo(1.0);
    }

    private static NocsProperties propsAstap(String binaryPath) {
        NocsProperties.PlateSolving.Astap astap = new NocsProperties.PlateSolving.Astap(binaryPath, "", "H18");
        NocsProperties.PlateSolving ps = new NocsProperties.PlateSolving(
                "astap", 60L, astap, new NocsProperties.PlateSolving.Install(false, "", Map.of(), "", ""));
        return new NocsProperties(null, null, null, null, null, null, null, ps);
    }

    private static ProcessRunner stubRunner(java.util.function.Consumer<List<String>> sink) {
        return (cmd, work, env, t) -> {
            sink.accept(cmd);
            return new ProcessResult(0, "", "", false, 0L);
        };
    }
}
