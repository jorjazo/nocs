package dev.nocs.platesolving;

import dev.nocs.device.DeviceId;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.image.CaptureContext;
import dev.nocs.image.FitsHeaderReader;
import dev.nocs.image.ImageRepository;
import dev.nocs.image.ImageStoreService;
import dev.nocs.image.MiniFits;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CopyOnWriteArrayList;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.test.context.TestPropertySource;
import reactor.core.Disposable;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@TestPropertySource(
        properties = {
            "nocs.auth.token=t",
            "nocs.platesolving.solver=astap"
        })
@Import(IntegrationPlateSolvingApiTest.StubSolverConfig.class)
class IntegrationPlateSolvingApiTest {

    @Autowired ImageStoreService store;
    @Autowired PlateSolutionRepository solutionRepo;
    @Autowired EventBus bus;
    @LocalServerPort int port;

    @Test
    void solveAmendsFitsAndPersistsSolution() throws Exception {
        DeviceId cam = new DeviceId("ccd-int");
        store.prepareCapture(cam, CaptureContext.defaults(60.0));
        byte[] originalFits = MiniFits.build16(8, 8, new short[64], Map.of(
                "DATE-OBS", "'2026-04-22T22:00:00'"));
        store.accept(cam, originalFits, ".fits");
        long imageId = store.list(new ImageRepository.Filters("ccd-int", null, null, null, 10, 0))
                .get(0)
                .id();

        List<Event> events = new CopyOnWriteArrayList<>();
        Disposable sub = bus.subscribe(Set.of(Topic.PLATESOLVING)).subscribe(events::add);

        HttpClient http = HttpClient.newHttpClient();
        HttpResponse<String> resp = http.send(
                HttpRequest.newBuilder(URI.create(base() + "/api/platesolving/solve"))
                        .header("Authorization", "Bearer t")
                        .header("Content-Type", "application/json")
                        .POST(HttpRequest.BodyPublishers.ofString(
                                "{\"image_id\":" + imageId + "}"))
                        .build(),
                HttpResponse.BodyHandlers.ofString());
        assertThat(resp.statusCode()).isEqualTo(200);
        assertThat(resp.body()).contains("\"solved\":true");

        Awaitility.await().atMost(Duration.ofSeconds(5))
                .untilAsserted(() -> assertThat(events)
                        .extracting(Event::type)
                        .contains("solve_started", "solved"));

        var rec = store.find(imageId).orElseThrow();
        byte[] reread = Files.readAllBytes(Path.of(rec.fitsPath()));
        FitsHeaderReader.Header h = FitsHeaderReader.read(reread);
        String header = new String(reread, 0, h.dataOffset(), StandardCharsets.US_ASCII);
        assertThat(header).contains("CRVAL1");
        assertThat(header).contains("CRVAL2");

        var row = solutionRepo.findByImageId(imageId).orElseThrow();
        assertThat(row.raJ2000Deg()).isEqualTo(10.6847083);
        assertThat(row.decJ2000Deg()).isEqualTo(41.269083);
        assertThat(row.solver()).isEqualTo("astap");
        sub.dispose();
    }

    private String base() {
        return "http://localhost:" + port;
    }

    @TestConfiguration
    static class StubSolverConfig {
        @Bean
        @Primary
        PlateSolvingService stubSolver() {
            return new PlateSolvingService() {
                @Override
                public SolveOutcome solve(byte[] fits, SolveOptions options) {
                    PlateSolution s = new PlateSolution(
                            10.6847083, 41.269083, 1.234, 12.5, 0.5, 0.4, Instant.now(), "astap");
                    return new SolveOutcome.Solved(s, 25L);
                }

                @Override
                public boolean isAvailable() {
                    return true;
                }
            };
        }
    }
}
