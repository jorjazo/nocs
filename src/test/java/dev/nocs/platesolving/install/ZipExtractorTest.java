package dev.nocs.platesolving.install;

import java.io.IOException;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.assertj.core.api.Assertions.assertThat;

class ZipExtractorTest {

    @Test
    void extractsNamedEntry(@TempDir Path tmp) throws IOException {
        Path zip = buildZip(tmp.resolve("ar.zip"),
                "astap_cli", "binary-bytes",
                "README.md", "README content");

        Path out = tmp.resolve("bin/astap_cli");
        new ZipExtractor().extractEntry(zip, "astap_cli", out);

        assertThat(Files.readString(out)).isEqualTo("binary-bytes");
    }

    @Test
    void extractAllPlacesEachEntry(@TempDir Path tmp) throws IOException {
        Path zip = buildZip(tmp.resolve("ar.zip"),
                "h18/h18_index.dat", "idx-bytes",
                "h18/h18_data.dat", "data-bytes");

        Path dest = tmp.resolve("db");
        new ZipExtractor().extractAll(zip, dest);

        assertThat(Files.readString(dest.resolve("h18/h18_index.dat"))).isEqualTo("idx-bytes");
        assertThat(Files.readString(dest.resolve("h18/h18_data.dat"))).isEqualTo("data-bytes");
    }

    private static Path buildZip(Path target, String... pairs) throws IOException {
        try (OutputStream out = Files.newOutputStream(target);
                ZipOutputStream zout = new ZipOutputStream(out)) {
            for (int i = 0; i < pairs.length; i += 2) {
                zout.putNextEntry(new ZipEntry(pairs[i]));
                zout.write(pairs[i + 1].getBytes());
                zout.closeEntry();
            }
        }
        return target;
    }
}
