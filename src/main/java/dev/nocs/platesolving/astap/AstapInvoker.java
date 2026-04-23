package dev.nocs.platesolving.astap;

import dev.nocs.platesolving.FailureKind;
import dev.nocs.platesolving.SolveOptions;
import dev.nocs.platesolving.SolveOutcome;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.Comparator;
import java.util.HashMap;
import java.util.Map;
import java.util.stream.Stream;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

@Component
public class AstapInvoker {

    private static final Logger log = LoggerFactory.getLogger(AstapInvoker.class);

    private final ProcessRunner runner;
    private final AstapIniParser parser;

    public AstapInvoker(ProcessRunner runner, AstapIniParser parser) {
        this.runner = runner;
        this.parser = parser;
    }

    public SolveOutcome invoke(AstapInstallation inst, byte[] fits, SolveOptions options, long timeoutSec) {
        return invoke(inst, fits, options, timeoutSec, Map.of());
    }

    public SolveOutcome invoke(
            AstapInstallation inst, byte[] fits, SolveOptions options, long timeoutSec,
            Map<String, String> envOverrides) {
        Path workDir = null;
        long start = System.currentTimeMillis();
        try {
            workDir = Files.createTempDirectory("nocs-astap-");
            Path fitsFile = workDir.resolve("input.fits");
            Files.write(fitsFile, fits);
            Map<String, String> env = new HashMap<>(envOverrides == null ? Map.of() : envOverrides);
            ProcessResult result = runner.run(
                    AstapInvocation.command(inst, fitsFile, options), workDir, env, timeoutSec);
            if (result.timedOut()) {
                return new SolveOutcome.Failed(
                        FailureKind.TIMEOUT,
                        "ASTAP exceeded " + timeoutSec + "s; stderr=" + truncate(result.stderr()),
                        result.durationMs());
            }
            Path ini = workDir.resolve("input.ini");
            String iniText = Files.exists(ini) ? Files.readString(ini) : "";
            if (iniText.isBlank()) {
                return new SolveOutcome.Failed(
                        FailureKind.INTERNAL_ERROR,
                        "ASTAP exit=" + result.exitCode()
                                + " stdout=" + truncate(result.stdout())
                                + " stderr=" + truncate(result.stderr()),
                        result.durationMs());
            }
            return parser.parse(iniText, result.durationMs(), Instant.now());
        } catch (IOException e) {
            return new SolveOutcome.Failed(
                    FailureKind.IO_ERROR, e.getMessage(), System.currentTimeMillis() - start);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return new SolveOutcome.Failed(
                    FailureKind.INTERNAL_ERROR, "interrupted", System.currentTimeMillis() - start);
        } finally {
            cleanup(workDir);
        }
    }

    private static void cleanup(Path dir) {
        if (dir == null || !Files.exists(dir)) {
            return;
        }
        try (Stream<Path> walk = Files.walk(dir)) {
            walk.sorted(Comparator.reverseOrder()).forEach(p -> {
                try {
                    Files.deleteIfExists(p);
                } catch (IOException ignored) {
                }
            });
        } catch (IOException e) {
            log.debug("astap workdir cleanup failed for {}: {}", dir, e.getMessage());
        }
    }

    private static String truncate(String s) {
        if (s == null) {
            return "";
        }
        return s.length() > 400 ? s.substring(0, 400) + "..." : s;
    }
}
