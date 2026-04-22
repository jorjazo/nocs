package dev.nocs.observatory;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@TestPropertySource(properties = "nocs.auth.token=t")
class V2MigrationTest {

    @Autowired JdbcTemplate jdbc;

    @Test
    void observatoriesTableExists() {
        Integer c = jdbc.queryForObject(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='observatories'",
                Integer.class);
        assertThat(c).isEqualTo(1);
    }

    @Test
    void targetsCustomTableExists() {
        Integer c = jdbc.queryForObject(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='targets_custom'",
                Integer.class);
        assertThat(c).isEqualTo(1);
    }

    @Test
    void observatoriesHasHorizonMaskColumn() {
        Integer c = jdbc.queryForObject(
                "SELECT COUNT(*) FROM pragma_table_info('observatories') WHERE name='horizon_mask_json'",
                Integer.class);
        assertThat(c).isEqualTo(1);
    }

    @Test
    void onlyOneActiveObservatoryIsEnforced() {
        jdbc.update("INSERT INTO observatories(name, latitude_deg, longitude_deg, elevation_m, is_active) "
                + "VALUES('Alpha', 10, 20, 30, 1)");
        jdbc.update("INSERT INTO observatories(name, latitude_deg, longitude_deg, elevation_m, is_active) "
                + "VALUES('Beta', 11, 21, 31, 0)");
        Integer actives = jdbc.queryForObject(
                "SELECT COUNT(*) FROM observatories WHERE is_active = 1", Integer.class);
        assertThat(actives).isEqualTo(1);
        jdbc.update("DELETE FROM observatories");
    }
}
