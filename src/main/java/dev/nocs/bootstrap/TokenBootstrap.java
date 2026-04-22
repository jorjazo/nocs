package dev.nocs.bootstrap;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.SecureRandom;
import java.util.Base64;

public final class TokenBootstrap {

    private static final String PLACEHOLDER = "GENERATE_ME";

    private TokenBootstrap() {}

    public static String ensureToken(Path configFile) throws IOException {
        String contents = Files.readString(configFile);
        String existing = extractToken(contents);
        if (existing != null && !existing.equals(PLACEHOLDER) && !existing.isBlank()) {
            return existing;
        }
        String generated = generate();
        String updated = contents.replaceFirst(
                "(?m)^(\\s*token:\\s*).*$",
                "$1" + generated);
        Files.writeString(configFile, updated);
        return generated;
    }

    static String generate() {
        byte[] buf = new byte[24];
        new SecureRandom().nextBytes(buf);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(buf);
    }

    static String extractToken(String yaml) {
        for (String line : yaml.split("\n")) {
            String trimmed = line.trim();
            if (trimmed.startsWith("token:")) {
                return trimmed.substring("token:".length()).trim();
            }
        }
        return null;
    }
}
