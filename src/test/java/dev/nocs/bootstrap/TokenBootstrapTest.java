package dev.nocs.bootstrap;

import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.assertj.core.api.Assertions.assertThat;

class TokenBootstrapTest {

    @Test
    void writesTokenWhenConfigAbsent(@TempDir Path tempDir) throws Exception {
        Path configFile = tempDir.resolve("config.yaml");
        Files.writeString(configFile, "auth:\n  token: GENERATE_ME\n");

        String token = TokenBootstrap.ensureToken(configFile);

        assertThat(token).isNotBlank().hasSizeGreaterThanOrEqualTo(32);
        assertThat(Files.readString(configFile)).contains("token: " + token);
    }

    @Test
    void keepsExistingToken(@TempDir Path tempDir) throws Exception {
        Path configFile = tempDir.resolve("config.yaml");
        Files.writeString(configFile, "auth:\n  token: abc123def456\n");

        String token = TokenBootstrap.ensureToken(configFile);

        assertThat(token).isEqualTo("abc123def456");
    }
}
