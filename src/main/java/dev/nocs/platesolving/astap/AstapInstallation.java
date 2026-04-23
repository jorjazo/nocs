package dev.nocs.platesolving.astap;

import java.nio.file.Path;

public record AstapInstallation(Path binary, Path dbDir, String dbName) {

    public AstapInstallation {
        if (binary == null) {
            throw new IllegalArgumentException("binary required");
        }
        if (dbDir == null) {
            throw new IllegalArgumentException("dbDir required");
        }
        if (dbName == null || dbName.isBlank()) {
            dbName = "H18";
        }
    }
}
