package dev.nocs.platesolving.install;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Duration;
import org.springframework.stereotype.Component;

@Component
public class HttpAstapDownloader implements AstapDownloader {

    private final HttpClient client = HttpClient.newBuilder()
            .followRedirects(HttpClient.Redirect.ALWAYS)
            .connectTimeout(Duration.ofSeconds(30))
            .build();

    @Override
    public void download(URI url, Path dest, ProgressListener listener) throws IOException {
        HttpRequest req = HttpRequest.newBuilder(url).GET().build();
        try {
            HttpResponse<InputStream> resp = client.send(req, HttpResponse.BodyHandlers.ofInputStream());
            if (resp.statusCode() / 100 != 2) {
                throw new IOException("HTTP " + resp.statusCode() + " for " + url);
            }
            long total = resp.headers().firstValueAsLong("Content-Length").orElse(-1L);
            Files.createDirectories(dest.getParent());
            try (InputStream in = resp.body();
                    OutputStream out = Files.newOutputStream(
                            dest, StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING)) {
                byte[] buf = new byte[64 * 1024];
                long done = 0;
                int n;
                while ((n = in.read(buf)) > 0) {
                    out.write(buf, 0, n);
                    done += n;
                    if (listener != null) {
                        listener.onBytes(done, total);
                    }
                }
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IOException("download interrupted", e);
        }
    }
}
