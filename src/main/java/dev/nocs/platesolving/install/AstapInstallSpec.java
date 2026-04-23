package dev.nocs.platesolving.install;

import java.net.URI;

public record AstapInstallSpec(
        URI binaryUrl,
        String binarySha256,
        ArchiveKind binaryKind,
        String binaryEntryName,
        URI dbUrl,
        String dbSha256,
        String dbName,
        ArchiveKind dbKind) {

    public AstapInstallSpec {
        if (binaryUrl == null) {
            throw new IllegalArgumentException("binaryUrl required");
        }
        if (dbUrl == null) {
            throw new IllegalArgumentException("dbUrl required");
        }
        if (binarySha256 == null || binarySha256.isBlank()) {
            throw new IllegalArgumentException("binarySha256 required");
        }
        if (dbSha256 == null || dbSha256.isBlank()) {
            throw new IllegalArgumentException("dbSha256 required");
        }
        if (binaryEntryName == null || binaryEntryName.isBlank()) {
            binaryEntryName = "astap_cli";
        }
        if (dbName == null || dbName.isBlank()) {
            dbName = "H18";
        }
        if (binaryKind == null) {
            binaryKind = ArchiveKind.ZIP;
        }
        if (dbKind == null) {
            dbKind = ArchiveKind.ZIP;
        }
    }
}
