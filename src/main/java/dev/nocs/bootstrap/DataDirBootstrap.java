package dev.nocs.bootstrap;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;

public final class DataDirBootstrap {

    private DataDirBootstrap() {}

    public static Path resolveDataDir() {
        String override = System.getenv("NOCS_DATA_DIR");
        if (override != null && !override.isBlank()) {
            return Paths.get(override).toAbsolutePath();
        }
        String os = System.getProperty("os.name", "").toLowerCase();
        if (os.contains("win")) {
            String appData = System.getenv("APPDATA");
            return Paths.get(appData == null ? System.getProperty("user.home") : appData, "nocs").toAbsolutePath();
        }
        String xdg = System.getenv("XDG_DATA_HOME");
        if (xdg != null && !xdg.isBlank()) {
            return Paths.get(xdg, "nocs").toAbsolutePath();
        }
        return Paths.get(System.getProperty("user.home"), ".local", "share", "nocs").toAbsolutePath();
    }

    public static Path ensureLayout(Path dataDir) throws IOException {
        Files.createDirectories(dataDir);
        Files.createDirectories(dataDir.resolve("sessions"));
        Files.createDirectories(dataDir.resolve("logs"));
        Files.createDirectories(dataDir.resolve("astap").resolve("bin"));
        Files.createDirectories(dataDir.resolve("astap").resolve("db"));
        Path configFile = copyIfMissing(dataDir, "config.example.yaml", "config.yaml");
        copyIfMissing(dataDir, "safety.example.yaml", "safety.yaml");
        return configFile;
    }

    private static Path copyIfMissing(Path dataDir, String resource, String target) throws IOException {
        Path dest = dataDir.resolve(target);
        if (Files.exists(dest)) {
            return dest;
        }
        try (InputStream in = DataDirBootstrap.class.getResourceAsStream("/" + resource)) {
            if (in == null) {
                throw new IOException(resource + " missing from classpath");
            }
            Files.copy(in, dest, StandardCopyOption.REPLACE_EXISTING);
        }
        return dest;
    }
}
