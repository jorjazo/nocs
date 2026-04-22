package dev.nocs.events;

import java.time.Instant;
import java.util.EnumSet;
import java.util.Map;
import org.junit.jupiter.api.Test;
import reactor.test.StepVerifier;

class EventBusTest {

    @Test
    void subscribersReceivePublishedEvents() {
        EventBus bus = new EventBus();
        Event e = new Event(Topic.SYSTEM, "ready", Instant.parse("2026-04-22T10:00:00Z"), Map.of());

        StepVerifier.create(bus.subscribe(EnumSet.of(Topic.SYSTEM)).take(1))
                .then(() -> bus.publish(e))
                .expectNext(e)
                .verifyComplete();
    }

    @Test
    void subscribersOnlySeeSelectedTopics() {
        EventBus bus = new EventBus();
        Event wanted = new Event(Topic.SYSTEM, "a", Instant.now(), Map.of());
        Event skipped = new Event(Topic.SESSION, "b", Instant.now(), Map.of());

        StepVerifier.create(bus.subscribe(EnumSet.of(Topic.SYSTEM)).take(1))
                .then(() -> {
                    bus.publish(skipped);
                    bus.publish(wanted);
                })
                .expectNext(wanted)
                .verifyComplete();
    }
}
