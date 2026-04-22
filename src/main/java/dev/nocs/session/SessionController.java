package dev.nocs.session;

import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/sessions")
public class SessionController {

    private final SessionService service;
    private final JdbcTemplate jdbc;

    public SessionController(SessionService service, JdbcTemplate jdbc) {
        this.service = service;
        this.jdbc = jdbc;
    }

    @PostMapping
    public Session open(@RequestBody Map<String, String> body) {
        return service.open(body.getOrDefault("name", "unnamed"));
    }

    @GetMapping
    public List<Map<String, Object>> list() {
        return jdbc.queryForList("SELECT id, name, opened_at, closed_at FROM sessions ORDER BY id DESC");
    }

    @GetMapping("/{id}")
    public Map<String, Object> get(@PathVariable long id) {
        Map<String, Object> row = jdbc.queryForMap(
                "SELECT id, name, opened_at, closed_at FROM sessions WHERE id = ?", id);
        List<Map<String, Object>> events = jdbc.queryForList(
                "SELECT id, ts, topic, type, payload_json FROM session_events WHERE session_id = ? ORDER BY id", id);
        return Map.of("session", row, "events", events);
    }

    @PostMapping("/{id}/close")
    public Map<String, String> close(@PathVariable long id) {
        Session current = service.current();
        if (current != null && current.id() == id) {
            service.close();
            return Map.of("status", "closed");
        }
        return Map.of("status", "not-active");
    }
}
