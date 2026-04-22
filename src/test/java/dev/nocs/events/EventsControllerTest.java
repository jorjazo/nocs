package dev.nocs.events;

import java.time.Duration;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.test.context.TestPropertySource;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Flux;
import reactor.test.StepVerifier;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@TestPropertySource(properties = "nocs.auth.token=t")
class EventsControllerTest {

    @Autowired
    EventBus bus;
    @LocalServerPort
    int port;

    @Test
    void streamDeliversPublishedEvent() {
        WebClient client = WebClient.builder()
                .baseUrl("http://localhost:" + port)
                .defaultHeader("Authorization", "Bearer t")
                .build();

        ParameterizedTypeReference<ServerSentEvent<Event>> type =
                new ParameterizedTypeReference<>() {};

        Flux<ServerSentEvent<Event>> stream = client.get()
                .uri("/api/events?topics=system")
                .accept(MediaType.TEXT_EVENT_STREAM)
                .retrieve()
                .bodyToFlux(type);

        StepVerifier.create(stream.take(1))
                .then(() -> {
                    try {
                        Thread.sleep(200);
                    } catch (InterruptedException ignored) {
                    }
                    bus.publish(Event.of(Topic.SYSTEM, "hello", Map.of("x", 1)));
                })
                .expectNextMatches(sse ->
                        sse.data() != null
                                && sse.data().topic() == Topic.SYSTEM
                                && "hello".equals(sse.data().type()))
                .thenCancel()
                .verify(Duration.ofSeconds(5));
    }
}
