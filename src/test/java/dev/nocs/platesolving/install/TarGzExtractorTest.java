package dev.nocs.platesolving.install;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Locale;
import java.util.zip.GZIPOutputStream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.assertj.core.api.Assertions.assertThat;

class TarGzExtractorTest {

    @Test
    void extractsRegularFile(@TempDir Path tmp) throws IOException {
        Path archive = tmp.resolve("astap.tar.gz");
        byte[] payload = "binary-bytes".getBytes(StandardCharsets.UTF_8);
        writeTarGz(archive, "astap_cli", payload);

        Path dest = tmp.resolve("bin/astap_cli");
        new TarGzExtractor().extractEntry(archive, "astap_cli", dest);

        assertThat(Files.readAllBytes(dest)).isEqualTo(payload);
    }

    private static void writeTarGz(Path target, String name, byte[] payload) throws IOException {
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        byte[] header = new byte[512];
        byte[] nameBytes = name.getBytes(StandardCharsets.US_ASCII);
        System.arraycopy(nameBytes, 0, header, 0, nameBytes.length);
        write(header, 100, "0000777 ", 8);
        write(header, 108, "0000000 ", 8);
        write(header, 116, "0000000 ", 8);
        write(header, 124, String.format(Locale.ROOT, "%011o ", payload.length), 12);
        write(header, 136, "00000000000 ", 12);
        for (int i = 148; i < 156; i++) {
            header[i] = ' ';
        }
        header[156] = '0';
        write(header, 257, "ustar ", 6);
        write(header, 263, " ", 2);
        long checksum = 0;
        for (byte b : header) {
            checksum += b & 0xff;
        }
        byte[] cs = String.format(Locale.ROOT, "%06o\0 ", checksum).getBytes(StandardCharsets.US_ASCII);
        System.arraycopy(cs, 0, header, 148, cs.length);

        buf.write(header);
        buf.write(payload);
        int pad = (512 - (payload.length % 512)) % 512;
        buf.write(new byte[pad]);
        buf.write(new byte[1024]);

        try (OutputStream out = new GZIPOutputStream(Files.newOutputStream(target))) {
            out.write(buf.toByteArray());
        }
    }

    private static void write(byte[] header, int offset, String text, int len) {
        byte[] b = text.getBytes(StandardCharsets.US_ASCII);
        System.arraycopy(b, 0, header, offset, Math.min(b.length, len));
    }
}
