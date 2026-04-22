package dev.nocs.config;

import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class ConfigKvRepository {

    private final JdbcTemplate jdbc;

    public ConfigKvRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public Map<String, String> findAll() {
        Map<String, String> out = new LinkedHashMap<>();
        jdbc.query("SELECT key, value FROM config_kv ORDER BY key",
                rs -> { out.put(rs.getString(1), rs.getString(2)); });
        return out;
    }

    public void upsert(String key, String value) {
        jdbc.update(
                "INSERT INTO config_kv(key, value, updated_at) VALUES(?, ?, datetime('now')) "
                + "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                key, value);
    }
}
