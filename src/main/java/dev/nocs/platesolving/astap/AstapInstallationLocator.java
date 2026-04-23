package dev.nocs.platesolving.astap;

import dev.nocs.config.NocsProperties;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Locale;
import java.util.Optional;
import org.springframework.stereotype.Component;

@Component
public class AstapInstallationLocator {

    public Optional<AstapInstallation> locate(NocsProperties props, Path dataDir) {
        NocsProperties.PlateSolving ps = props.platesolving();
        String dbName = ps == null || ps.astap() == null ? "H18" : ps.astap().dbName();

        Path binary = resolveBinary(ps, dataDir);
        if (binary == null) {
            return Optional.empty();
        }
        Path dbDir = resolveDb(ps, dataDir);
        if (dbDir == null || !hasDb(dbDir, dbName)) {
            return Optional.empty();
        }
        return Optional.of(new AstapInstallation(binary, dbDir, dbName));
    }

    private Path resolveBinary(NocsProperties.PlateSolving ps, Path dataDir) {
        if (ps != null
                && ps.astap() != null
                && ps.astap().binaryPath() != null
                && !ps.astap().binaryPath().isBlank()) {
            Path p = Paths.get(ps.astap().binaryPath());
            if (Files.isExecutable(p)) {
                return p;
            }
        }
        Path under = dataDir.resolve("astap").resolve("bin").resolve(executableName());
        if (Files.isExecutable(under)) {
            return under;
        }
        return findOnPath(executableName());
    }

    private Path resolveDb(NocsProperties.PlateSolving ps, Path dataDir) {
        if (ps != null
                && ps.astap() != null
                && ps.astap().dbDir() != null
                && !ps.astap().dbDir().isBlank()) {
            Path p = Paths.get(ps.astap().dbDir());
            return Files.isDirectory(p) ? p : null;
        }
        Path under = dataDir.resolve("astap").resolve("db");
        return Files.isDirectory(under) ? under : null;
    }

    private static boolean hasDb(Path dbDir, String dbName) {
        String prefix = dbName.toLowerCase(Locale.ROOT) + "_star_database";
        try (var stream = Files.list(dbDir)) {
            return stream.anyMatch(
                    p -> p.getFileName().toString().toLowerCase(Locale.ROOT).startsWith(prefix));
        } catch (Exception e) {
            return false;
        }
    }

    private static String executableName() {
        return System.getProperty("os.name", "").toLowerCase(Locale.ROOT).contains("win")
                ? "astap_cli.exe"
                : "astap_cli";
    }

    private static Path findOnPath(String name) {
        String path = System.getenv("PATH");
        if (path == null) {
            return null;
        }
        String sep = System.getProperty("path.separator", ":");
        for (String dir : path.split(sep)) {
            if (dir.isBlank()) {
                continue;
            }
            Path candidate = Paths.get(dir, name);
            if (Files.isExecutable(candidate)) {
                return candidate;
            }
        }
        return null;
    }
}
