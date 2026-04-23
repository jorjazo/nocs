package dev.nocs.platesolving.install;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Locale;
import org.springframework.stereotype.Component;

@Component
public class AstapInstaller {

    private final AstapDownloader downloader;
    private final Sha256Verifier verifier;
    private final ZipExtractor zip;
    private final TarGzExtractor tar;

    public AstapInstaller(
            AstapDownloader downloader, Sha256Verifier verifier, ZipExtractor zip, TarGzExtractor tar) {
        this.downloader = downloader;
        this.verifier = verifier;
        this.zip = zip;
        this.tar = tar;
    }

    public Path install(AstapInstallSpec spec, Path dataDir, InstallEvents events) throws IOException {
        Path astapRoot = dataDir.resolve("astap");
        Path binDir = astapRoot.resolve("bin");
        Path dbDir = astapRoot.resolve("db");
        Path downDir = astapRoot.resolve("downloads");
        Files.createDirectories(binDir);
        Files.createDirectories(dbDir);
        Files.createDirectories(downDir);

        Path binaryArchive = downDir.resolve("binary" + extensionFor(spec.binaryKind()));
        Path dbArchive = downDir.resolve("db" + extensionFor(spec.dbKind()));

        events.phase(InstallPhase.DOWNLOADING_BINARY, "downloading ASTAP binary");
        downloader.download(
                spec.binaryUrl(), binaryArchive, (done, total) -> events.bytes(InstallPhase.DOWNLOADING_BINARY, done, total));

        events.phase(InstallPhase.VERIFYING_BINARY, "verifying binary checksum");
        verifier.verify(binaryArchive, spec.binarySha256());

        events.phase(InstallPhase.EXTRACTING_BINARY, "extracting binary");
        Path binFile = binDir.resolve(spec.binaryEntryName());
        switch (spec.binaryKind()) {
            case ZIP -> zip.extractEntry(binaryArchive, spec.binaryEntryName(), binFile);
            case TAR_GZ -> tar.extractEntry(binaryArchive, spec.binaryEntryName(), binFile);
            case RAW -> Files.copy(binaryArchive, binFile, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        }
        binFile.toFile().setExecutable(true);

        events.phase(InstallPhase.DOWNLOADING_DB, "downloading star DB " + spec.dbName());
        downloader.download(
                spec.dbUrl(), dbArchive, (done, total) -> events.bytes(InstallPhase.DOWNLOADING_DB, done, total));

        events.phase(InstallPhase.VERIFYING_DB, "verifying DB checksum");
        verifier.verify(dbArchive, spec.dbSha256());

        events.phase(InstallPhase.EXTRACTING_DB, "extracting DB");
        switch (spec.dbKind()) {
            case ZIP -> zip.extractAll(dbArchive, dbDir);
            case TAR_GZ -> tar.extractAll(dbArchive, dbDir);
            case RAW -> Files.copy(
                    dbArchive,
                    dbDir.resolve(spec.dbName().toLowerCase(Locale.ROOT) + "_star_database.dat"),
                    java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        }

        events.phase(InstallPhase.DONE, "install complete");
        return binFile;
    }

    private static String extensionFor(ArchiveKind kind) {
        return switch (kind) {
            case ZIP -> ".zip";
            case TAR_GZ -> ".tar.gz";
            case RAW -> ".bin";
        };
    }

    /** Callbacks fired by the installer during a run; the install service implements this. */
    public interface InstallEvents {
        void phase(InstallPhase phase, String message);

        void bytes(InstallPhase phase, long done, long total);
    }
}
