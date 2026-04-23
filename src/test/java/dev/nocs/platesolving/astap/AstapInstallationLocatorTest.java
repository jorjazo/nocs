package dev.nocs.platesolving.astap;

import dev.nocs.config.NocsProperties;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.assertj.core.api.Assertions.assertThat;

class AstapInstallationLocatorTest {

    @Test
    void prefersExplicitConfigPath(@TempDir Path tmp) throws Exception {
        Path bin = Files.createDirectories(tmp.resolve("custom")).resolve("astap_cli");
        Files.writeString(bin, "#!/usr/bin/env bash\nexit 0\n");
        bin.toFile().setExecutable(true);
        Path db = Files.createDirectories(tmp.resolve("dbs"));
        Files.createFile(db.resolve("h18_star_database_index.dat"));

        NocsProperties props = propsWith(bin.toString(), db.toString(), "H18");

        Optional<AstapInstallation> out = new AstapInstallationLocator().locate(props, tmp.resolve("data"));

        assertThat(out).isPresent();
        assertThat(out.get().binary()).isEqualTo(bin);
        assertThat(out.get().dbDir()).isEqualTo(db);
        assertThat(out.get().dbName()).isEqualTo("H18");
    }

    @Test
    void fallsBackToDataDirInstall(@TempDir Path data) throws Exception {
        Path bin = Files.createDirectories(data.resolve("astap/bin")).resolve("astap_cli");
        Files.writeString(bin, "#!/usr/bin/env bash\nexit 0\n");
        bin.toFile().setExecutable(true);
        Files.createDirectories(data.resolve("astap/db"));
        Files.createFile(data.resolve("astap/db/h18_star_database_index.dat"));

        Optional<AstapInstallation> out =
                new AstapInstallationLocator().locate(propsWith("", "", "H18"), data);

        assertThat(out).isPresent();
        assertThat(out.get().binary()).isEqualTo(bin);
    }

    @Test
    void returnsEmptyWhenBinaryIsMissing(@TempDir Path data) {
        Optional<AstapInstallation> out =
                new AstapInstallationLocator().locate(propsWith("", "", "H18"), data);

        assertThat(out).isEmpty();
    }

    @Test
    void returnsEmptyWhenDbIsMissing(@TempDir Path data) throws Exception {
        Path bin = Files.createDirectories(data.resolve("astap/bin")).resolve("astap_cli");
        Files.writeString(bin, "#!/usr/bin/env bash\nexit 0\n");
        bin.toFile().setExecutable(true);

        Optional<AstapInstallation> out =
                new AstapInstallationLocator().locate(propsWith("", "", "H18"), data);

        assertThat(out).isEmpty();
    }

    private static NocsProperties propsWith(String bin, String db, String dbName) {
        NocsProperties.PlateSolving.Astap astap = new NocsProperties.PlateSolving.Astap(bin, db, dbName);
        NocsProperties.PlateSolving ps = new NocsProperties.PlateSolving(
                "astap", 60L, astap, new NocsProperties.PlateSolving.Install(false, "", Map.of(), "", ""));
        return new NocsProperties(null, null, null, null, null, null, null, ps);
    }
}
