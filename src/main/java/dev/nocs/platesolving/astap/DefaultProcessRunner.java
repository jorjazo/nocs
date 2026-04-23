package dev.nocs.platesolving.astap;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import org.springframework.stereotype.Component;

@Component
public class DefaultProcessRunner implements ProcessRunner {

    @Override
    public ProcessResult run(
            List<String> command,
            Path workDir,
            Map<String, String> envOverrides,
            long timeoutSec) throws IOException, InterruptedException {
        long start = System.currentTimeMillis();
        ProcessBuilder pb = new ProcessBuilder(command);
        pb.directory(workDir.toFile());
        pb.redirectErrorStream(false);
        if (envOverrides != null) {
            pb.environment().putAll(envOverrides);
        }
        Process p = pb.start();
        boolean done = p.waitFor(Math.max(1L, timeoutSec), TimeUnit.SECONDS);
        long duration = System.currentTimeMillis() - start;
        if (!done) {
            p.destroy();
            if (!p.waitFor(2, TimeUnit.SECONDS)) {
                p.destroyForcibly();
            }
            return new ProcessResult(-1, drainQuiet(p.getInputStream()), drainQuiet(p.getErrorStream()), true, duration);
        }
        return new ProcessResult(
                p.exitValue(), drainQuiet(p.getInputStream()), drainQuiet(p.getErrorStream()), false, duration);
    }

    private static String drainQuiet(InputStream in) {
        try {
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException e) {
            return "";
        }
    }
}
