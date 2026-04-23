package dev.nocs.platesolving.install;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Locale;
import org.springframework.stereotype.Component;

@Component
public class Sha256Verifier {

    public void verify(Path file, String expectedHex) throws IOException {
        if (expectedHex == null || expectedHex.isBlank()) {
            throw new IOException("expected sha256 missing");
        }
        String actual = compute(file);
        if (!actual.equalsIgnoreCase(expectedHex.trim())) {
            throw new IOException(
                    "sha256 mismatch for " + file.getFileName()
                            + ": expected=" + expectedHex + " actual=" + actual);
        }
    }

    public String compute(Path file) throws IOException {
        MessageDigest md;
        try {
            md = MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException e) {
            throw new IOException(e);
        }
        try (InputStream in = Files.newInputStream(file)) {
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) {
                md.update(buf, 0, n);
            }
        }
        byte[] digest = md.digest();
        StringBuilder sb = new StringBuilder(digest.length * 2);
        for (byte b : digest) {
            sb.append(String.format(Locale.ROOT, "%02x", b));
        }
        return sb.toString();
    }
}
