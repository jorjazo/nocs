package dev.nocs.platesolving.install;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;
import org.springframework.stereotype.Component;

@Component
public class ZipExtractor {

    public void extractEntry(Path zipFile, String entryName, Path destFile) throws IOException {
        try (InputStream raw = Files.newInputStream(zipFile);
                ZipInputStream zin = new ZipInputStream(raw)) {
            ZipEntry e;
            while ((e = zin.getNextEntry()) != null) {
                if (matches(e.getName(), entryName)) {
                    Files.createDirectories(destFile.getParent());
                    try (OutputStream out = Files.newOutputStream(
                            destFile, StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING)) {
                        zin.transferTo(out);
                    }
                    return;
                }
            }
        }
        throw new IOException("entry " + entryName + " not found in " + zipFile);
    }

    public void extractAll(Path zipFile, Path destDir) throws IOException {
        Files.createDirectories(destDir);
        try (InputStream raw = Files.newInputStream(zipFile);
                ZipInputStream zin = new ZipInputStream(raw)) {
            ZipEntry e;
            while ((e = zin.getNextEntry()) != null) {
                Path target = destDir.resolve(e.getName()).normalize();
                if (!target.startsWith(destDir)) {
                    throw new IOException("zip slip: " + e.getName());
                }
                if (e.isDirectory()) {
                    Files.createDirectories(target);
                    continue;
                }
                Files.createDirectories(target.getParent());
                try (OutputStream out = Files.newOutputStream(
                        target, StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING)) {
                    zin.transferTo(out);
                }
            }
        }
    }

    private static boolean matches(String entryName, String wanted) {
        if (entryName.equals(wanted)) {
            return true;
        }
        int slash = entryName.lastIndexOf('/');
        return slash >= 0 && entryName.substring(slash + 1).equals(wanted);
    }
}
