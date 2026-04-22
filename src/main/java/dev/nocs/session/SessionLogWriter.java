package dev.nocs.session;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.time.format.DateTimeFormatter;

public class SessionLogWriter implements AutoCloseable {

    private final Path path;
    private final BufferedWriter writer;

    public SessionLogWriter(Path path) throws IOException {
        Files.createDirectories(path.getParent());
        this.path = path;
        this.writer = Files.newBufferedWriter(path,
                StandardOpenOption.CREATE, StandardOpenOption.APPEND);
    }

    public synchronized void write(String topic, String type, String payloadJson) {
        try {
            writer.write(DateTimeFormatter.ISO_INSTANT.format(Instant.now()));
            writer.write("  [");
            writer.write(topic);
            writer.write("] ");
            writer.write(type);
            writer.write("  ");
            writer.write(payloadJson);
            writer.newLine();
            writer.flush();
        } catch (IOException e) {
            throw new RuntimeException("session log write failed: " + path, e);
        }
    }

    public Path path() {
        return path;
    }

    @Override
    public synchronized void close() throws IOException {
        writer.close();
    }
}
