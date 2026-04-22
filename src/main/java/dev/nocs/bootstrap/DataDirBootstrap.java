package dev.nocs.bootstrap;

import java.io.IOException;
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
        Path configFile = dataDir.resolve("config.yaml");
        if (!Files.exists(configFile)) {
            try (var in = DataDirBootstrap.class.getResourceAsStream("/config.example.yaml")) {
                if (in == null) {
                    throw new IOException("config.example.yaml missing from classpath");
                }
                Files.copy(in, configFile, StandardCopyOption.REPLACE_EXISTING);
            }
        }
        return configFile;
    }
}
