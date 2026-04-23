package dev.nocs.safety;

import dev.nocs.bootstrap.DataDirBootstrap;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.assertj.core.api.Assertions.assertThat;

class SafetyExampleYamlBootstrapTest {

    @Test
    void firstRunCopiesSafetyExample(@TempDir Path tmp) throws IOException {
        DataDirBootstrap.ensureLayout(tmp);

        Path safetyYaml = tmp.resolve("safety.yaml");
        assertThat(Files.exists(safetyYaml)).isTrue();
        String contents = Files.readString(safetyYaml);
        assertThat(contents).contains("rain_detected");
        assertThat(contents).contains("e_stop");
    }

    @Test
    void secondRunDoesNotOverwriteUserEdits(@TempDir Path tmp) throws IOException {
        DataDirBootstrap.ensureLayout(tmp);
        Path safetyYaml = tmp.resolve("safety.yaml");
        Files.writeString(safetyYaml, "rules: []\n");

        DataDirBootstrap.ensureLayout(tmp);

        assertThat(Files.readString(safetyYaml)).isEqualTo("rules: []\n");
    }
}
