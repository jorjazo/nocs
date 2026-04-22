package dev.nocs.session;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
class SessionServiceTest {

    @Autowired
    SessionService service;
    @Autowired
    JdbcTemplate jdbc;

    @Test
    void openCreatesRowAndLogFile() throws Exception {
        Session s = service.open("test-session");

        Integer count = jdbc.queryForObject(
                "SELECT COUNT(*) FROM sessions WHERE id = ?", Integer.class, s.id());
        assertThat(count).isEqualTo(1);
        assertThat(Files.exists(Path.of(s.logPath()))).isTrue();

        service.logEvent("system", "probe", Map.of("k", "v"));

        Integer events = jdbc.queryForObject(
                "SELECT COUNT(*) FROM session_events WHERE session_id = ?", Integer.class, s.id());
        assertThat(events).isEqualTo(1);
        assertThat(Files.readString(Path.of(s.logPath()))).contains("probe");

        service.close();

        String closedAt = jdbc.queryForObject(
                "SELECT closed_at FROM sessions WHERE id = ?", String.class, s.id());
        assertThat(closedAt).isNotBlank();
    }
}
