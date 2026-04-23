package dev.nocs.platesolving.astap;

import java.io.IOException;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;

public interface ProcessRunner {
    ProcessResult run(
            List<String> command,
            Path workDir,
            Map<String, String> envOverrides,
            long timeoutSec) throws IOException, InterruptedException;
}
