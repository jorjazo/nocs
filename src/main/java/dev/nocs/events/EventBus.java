package dev.nocs.events;

import java.util.Set;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Sinks;

@Component
public class EventBus {

    private final Sinks.Many<Event> sink = Sinks.many().multicast().onBackpressureBuffer(1024, false);

    public void publish(Event event) {
        sink.tryEmitNext(event);
    }

    public Flux<Event> subscribe(Set<Topic> topics) {
        return sink.asFlux().filter(e -> topics.contains(e.topic()));
    }

    public Flux<Event> subscribeAll() {
        return sink.asFlux();
    }
}
