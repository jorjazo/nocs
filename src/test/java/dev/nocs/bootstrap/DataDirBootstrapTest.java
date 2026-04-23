package dev.nocs.bootstrap;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class DataDirBootstrapTest {

    @Test
    void ensureLayoutCreatesAstapDirs(@TempDir Path tmp) throws Exception {
        DataDirBootstrap.ensureLayout(tmp);
        assertThat(Files.isDirectory(tmp.resolve("astap/bin"))).isTrue();
        assertThat(Files.isDirectory(tmp.resolve("astap/db"))).isTrue();
    }
}
