package dev.nocs.platesolving.install;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class Sha256VerifierTest {

    @Test
    void computeMatchesKnownDigest(@TempDir Path tmp) throws IOException {
        Path file = tmp.resolve("hello.txt");
        Files.writeString(file, "hello\n");
        String hex = new Sha256Verifier().compute(file);
        assertThat(hex).isEqualTo("5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03");
    }

    @Test
    void verifyThrowsOnMismatch(@TempDir Path tmp) throws IOException {
        Path file = tmp.resolve("hello.txt");
        Files.writeString(file, "hello\n");
        assertThatThrownBy(() -> new Sha256Verifier().verify(file, "deadbeef"))
                .isInstanceOf(IOException.class)
                .hasMessageContaining("mismatch");
    }
}
