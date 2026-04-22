package dev.nocs.events;

import java.time.Duration;
import java.util.EnumSet;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Flux;

@RestController
@RequestMapping("/api/events")
public class EventsController {

    private final EventBus bus;

    public EventsController(EventBus bus) {
        this.bus = bus;
    }

    @GetMapping(produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public Flux<ServerSentEvent<Event>> stream(
            @RequestParam(name = "topics", required = false) List<String> topics) {

        Set<Topic> selected = (topics == null || topics.isEmpty())
                ? EnumSet.allOf(Topic.class)
                : topics.stream().map(Topic::fromWire).collect(Collectors.toCollection(() -> EnumSet.noneOf(Topic.class)));

        Flux<ServerSentEvent<Event>> events = bus.subscribe(selected)
                .map(e -> ServerSentEvent.builder(e).event(e.type()).build());
        Flux<ServerSentEvent<Event>> heartbeats = Flux.interval(Duration.ofSeconds(15))
                .map(i -> ServerSentEvent.<Event>builder().comment("heartbeat").build());

        return Flux.merge(events, heartbeats);
    }
}
