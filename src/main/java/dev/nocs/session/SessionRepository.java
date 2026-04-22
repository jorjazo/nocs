package dev.nocs.session;

import java.sql.Statement;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Repository;

@Repository
public class SessionRepository {

    private final JdbcTemplate jdbc;

    public SessionRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public long insert(String name) {
        GeneratedKeyHolder key = new GeneratedKeyHolder();
        jdbc.update(con -> {
            var ps = con.prepareStatement(
                    "INSERT INTO sessions(name) VALUES(?)", Statement.RETURN_GENERATED_KEYS);
            ps.setString(1, name);
            return ps;
        }, key);
        return key.getKey().longValue();
    }

    public void markClosed(long id) {
        jdbc.update("UPDATE sessions SET closed_at = datetime('now') WHERE id = ?", id);
    }

    public void insertEvent(long sessionId, String topic, String type, String payloadJson) {
        jdbc.update(
                "INSERT INTO session_events(session_id, topic, type, payload_json) VALUES(?, ?, ?, ?)",
                sessionId, topic, type, payloadJson);
    }
}
