package dev.nocs.target;

import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Optional;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SimbadResolverTest {

    @Test
    void offlineWhenDisabled() {
        SimbadResolver r = new SimbadResolver(false, "http://localhost:1/simbad");
        assertThat(r.resolve("M31")).isEmpty();
    }

    @Test
    void parsesCapturedFixture() throws Exception {
        byte[] body = Files.readAllBytes(Path.of(
                getClass().getResource("/simbad/m31-response.txt").toURI()));
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/sim-id", exchange -> {
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();
        try {
            String base = "http://127.0.0.1:" + server.getAddress().getPort();
            SimbadResolver r = new SimbadResolver(true, base);
            Optional<Target> out = r.resolve("M31");
            assertThat(out).isPresent();
            Target t = out.get();
            assertThat(t.id()).isEqualTo("simbad:M31");
            assertThat(t.raJ2000Deg()).isBetween(10.6, 10.8);
            assertThat(t.decJ2000Deg()).isBetween(41.2, 41.3);
        } finally {
            server.stop(0);
        }
    }

    @Test
    void returnsEmptyOnHttpError() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/sim-id", exchange -> {
            exchange.sendResponseHeaders(500, 0);
            exchange.close();
        });
        server.start();
        try {
            SimbadResolver r = new SimbadResolver(true, "http://127.0.0.1:" + server.getAddress().getPort());
            assertThat(r.resolve("x")).isEmpty();
        } finally {
            server.stop(0);
        }
    }
}
