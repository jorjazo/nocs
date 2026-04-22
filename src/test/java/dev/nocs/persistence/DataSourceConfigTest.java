package dev.nocs.persistence;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
class DataSourceConfigTest {

    @Autowired
    JdbcTemplate jdbcTemplate;

    @Test
    void flywayCreatesConfigKvTable() {
        Integer count = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='config_kv'",
                Integer.class);
        assertThat(count).isEqualTo(1);
    }

    @Test
    void flywayCreatesSessionsTable() {
        Integer count = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='sessions'",
                Integer.class);
        assertThat(count).isEqualTo(1);
    }

    @Test
    void flywayCreatesSessionEventsTable() {
        Integer count = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='session_events'",
                Integer.class);
        assertThat(count).isEqualTo(1);
    }
}
