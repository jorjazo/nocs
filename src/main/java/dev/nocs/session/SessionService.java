package dev.nocs.session;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.nocs.config.NocsProperties;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import jakarta.annotation.PreDestroy;
import java.io.IOException;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDate;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
import org.springframework.stereotype.Service;

@Service
public class SessionService {

    private final SessionRepository repo;
    private final EventBus bus;
    private final ObjectMapper mapper;
    private final Path logsRoot;
    private final AtomicReference<Active> active = new AtomicReference<>();

    public SessionService(SessionRepository repo, EventBus bus, ObjectMapper mapper, NocsProperties props) {
        this.repo = repo;
        this.bus = bus;
        this.mapper = mapper;
        String dataDir = props.dataDir() == null ? System.getProperty("java.io.tmpdir") : props.dataDir();
        this.logsRoot = Paths.get(dataDir, "logs");
    }

    public synchronized Session open(String name) {
        closeLocked();
        long id = repo.insert(name);
        Path logPath = logsRoot.resolve("session-" + LocalDate.now() + "-" + id + ".log");
        SessionLogWriter writer;
        try {
            writer = new SessionLogWriter(logPath);
        } catch (IOException e) {
            throw new RuntimeException("could not open session log: " + logPath, e);
        }
        Session s = new Session(id, name, java.time.Instant.now(), null, logPath.toString());
        active.set(new Active(s, writer));
        bus.publish(Event.of(Topic.SESSION, "opened", Map.of("id", id, "name", name)));
        return s;
    }

    public Session current() {
        Active a = active.get();
        return a == null ? null : a.session;
    }

    public synchronized void close() {
        closeLocked();
    }

    private void closeLocked() {
        Active a = active.getAndSet(null);
        if (a == null) {
            return;
        }
        repo.markClosed(a.session.id());
        try {
            a.writer.close();
        } catch (IOException ignored) {
            // best-effort close
        }
        bus.publish(Event.of(Topic.SESSION, "closed", Map.of("id", a.session.id())));
    }

    public void logEvent(String topic, String type, Map<String, Object> payload) {
        Active a = active.get();
        if (a == null) {
            return;
        }
        String json;
        try {
            json = mapper.writeValueAsString(payload == null ? Map.of() : payload);
        } catch (JsonProcessingException e) {
            json = "{}";
        }
        repo.insertEvent(a.session.id(), topic, type, json);
        a.writer.write(topic, type, json);
    }

    @PreDestroy
    public void shutdown() {
        close();
    }

    private record Active(Session session, SessionLogWriter writer) {}
}
