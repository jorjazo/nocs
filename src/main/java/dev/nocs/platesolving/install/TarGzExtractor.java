package dev.nocs.platesolving.install;

import java.io.BufferedInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.zip.GZIPInputStream;
import org.springframework.stereotype.Component;

/** Minimal pure-Java tar.gz reader: handles 512-byte headers, ustar names, and regular files. */
@Component
public class TarGzExtractor {

    private static final int BLOCK = 512;

    public void extractEntry(Path archive, String entryName, Path destFile) throws IOException {
        try (InputStream in = openGz(archive)) {
            TarHeader header;
            while ((header = readHeader(in)) != null) {
                if (matches(header.name, entryName) && header.typeFlag == '0') {
                    Files.createDirectories(destFile.getParent());
                    try (OutputStream out = Files.newOutputStream(
                            destFile, StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING)) {
                        copy(in, out, header.size);
                    }
                    skipPadding(in, header.size);
                    return;
                } else {
                    skipPadding(in, header.size);
                }
            }
        }
        throw new IOException("entry " + entryName + " not found in " + archive);
    }

    public void extractAll(Path archive, Path destDir) throws IOException {
        Files.createDirectories(destDir);
        try (InputStream in = openGz(archive)) {
            TarHeader header;
            while ((header = readHeader(in)) != null) {
                Path target = destDir.resolve(header.name).normalize();
                if (!target.startsWith(destDir)) {
                    throw new IOException("tar slip: " + header.name);
                }
                if (header.typeFlag == '5') {
                    Files.createDirectories(target);
                } else if (header.typeFlag == '0' || header.typeFlag == 0) {
                    Files.createDirectories(target.getParent());
                    try (OutputStream out = Files.newOutputStream(
                            target, StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING)) {
                        copy(in, out, header.size);
                    }
                } else {
                    skipExactly(in, header.size);
                }
                skipPadding(in, header.size);
            }
        }
    }

    private static InputStream openGz(Path archive) throws IOException {
        return new BufferedInputStream(new GZIPInputStream(Files.newInputStream(archive)));
    }

    private static TarHeader readHeader(InputStream in) throws IOException {
        byte[] block = in.readNBytes(BLOCK);
        if (block.length < BLOCK) {
            return null;
        }
        boolean allZero = true;
        for (byte b : block) {
            if (b != 0) {
                allZero = false;
                break;
            }
        }
        if (allZero) {
            return null;
        }
        String name = trimNul(new String(block, 0, 100, StandardCharsets.US_ASCII));
        long size = parseOctal(block, 124, 12);
        char typeFlag = (char) block[156];
        if ((char) block[257] == 'u' && (char) block[258] == 's' && (char) block[259] == 't') {
            String prefix = trimNul(new String(block, 345, 155, StandardCharsets.US_ASCII));
            if (!prefix.isEmpty()) {
                name = prefix + "/" + name;
            }
        }
        return new TarHeader(name, size, typeFlag);
    }

    private static void copy(InputStream in, OutputStream out, long size) throws IOException {
        byte[] buf = new byte[8192];
        long remaining = size;
        while (remaining > 0) {
            int want = (int) Math.min(buf.length, remaining);
            int read = in.read(buf, 0, want);
            if (read <= 0) {
                throw new IOException("tar truncated");
            }
            out.write(buf, 0, read);
            remaining -= read;
        }
    }

    private static void skipPadding(InputStream in, long size) throws IOException {
        long mod = size % BLOCK;
        if (mod != 0) {
            skipExactly(in, BLOCK - mod);
        }
    }

    private static void skipExactly(InputStream in, long n) throws IOException {
        long remaining = n;
        byte[] buf = new byte[(int) Math.min(8192, n)];
        while (remaining > 0) {
            int want = (int) Math.min(buf.length, remaining);
            int read = in.read(buf, 0, want);
            if (read <= 0) {
                throw new IOException("tar truncated");
            }
            remaining -= read;
        }
    }

    private static long parseOctal(byte[] block, int offset, int len) {
        long v = 0;
        for (int i = offset; i < offset + len; i++) {
            byte b = block[i];
            if (b == 0 || b == ' ') {
                continue;
            }
            v = (v << 3) + (b - '0');
        }
        return v;
    }

    private static String trimNul(String s) {
        int nul = s.indexOf('\0');
        return (nul >= 0 ? s.substring(0, nul) : s).trim();
    }

    private static boolean matches(String entryName, String wanted) {
        if (entryName.equals(wanted)) {
            return true;
        }
        int slash = entryName.lastIndexOf('/');
        return slash >= 0 && entryName.substring(slash + 1).equals(wanted);
    }

    private record TarHeader(String name, long size, char typeFlag) {}
}
