package dev.nocs.platesolving.install;

import java.io.IOException;
import java.io.OutputStream;
import java.net.URI;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.assertj.core.api.Assertions.assertThat;

class AstapInstallerTest {

    @Test
    void installCopiesBinaryAndDbAndFiresPhases(@TempDir Path tmp) throws IOException {
        Path binaryZip = tmp.resolve("astap.zip");
        buildZip(binaryZip, "astap_cli", "ASTAP-FAKE-BINARY");
        Path dbZip = tmp.resolve("h18.zip");
        buildZip(dbZip, "h18_star_database_index.dat", "INDEX", "h18_star_database_data.dat", "DATA");

        Sha256Verifier verifier = new Sha256Verifier();
        String binSha = verifier.compute(binaryZip);
        String dbSha = verifier.compute(dbZip);

        AstapInstallSpec spec = new AstapInstallSpec(
                binaryZip.toUri(),
                binSha,
                ArchiveKind.ZIP,
                "astap_cli",
                dbZip.toUri(),
                dbSha,
                "H18",
                ArchiveKind.ZIP);

        AstapDownloader downloader = (url, dest, listener) -> {
            Files.createDirectories(dest.getParent());
            Files.copy(Path.of(url), dest, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
            if (listener != null) {
                listener.onBytes(Files.size(dest), Files.size(dest));
            }
        };

        AstapInstaller installer = new AstapInstaller(downloader, verifier, new ZipExtractor(), new TarGzExtractor());

        Path dataDir = tmp.resolve("data");
        List<InstallPhase> phases = new ArrayList<>();
        AstapInstaller.InstallEvents events = new AstapInstaller.InstallEvents() {
            @Override
            public void phase(InstallPhase p, String m) {
                phases.add(p);
            }

            @Override
            public void bytes(InstallPhase p, long d, long t) {}
        };

        Path bin = installer.install(spec, dataDir, events);

        assertThat(Files.readString(bin)).isEqualTo("ASTAP-FAKE-BINARY");
        assertThat(Files.readString(dataDir.resolve("astap/db/h18_star_database_index.dat")))
                .isEqualTo("INDEX");
        assertThat(phases)
                .contains(
                        InstallPhase.DOWNLOADING_BINARY,
                        InstallPhase.VERIFYING_BINARY,
                        InstallPhase.EXTRACTING_BINARY,
                        InstallPhase.DOWNLOADING_DB,
                        InstallPhase.VERIFYING_DB,
                        InstallPhase.EXTRACTING_DB,
                        InstallPhase.DONE);
        assertThat(bin.toFile().canExecute()).isTrue();
    }

    private static void buildZip(Path target, String... pairs) throws IOException {
        try (OutputStream out = Files.newOutputStream(target);
                ZipOutputStream zout = new ZipOutputStream(out)) {
            for (int i = 0; i < pairs.length; i += 2) {
                zout.putNextEntry(new ZipEntry(pairs[i]));
                zout.write(pairs[i + 1].getBytes());
                zout.closeEntry();
            }
        }
    }
}
