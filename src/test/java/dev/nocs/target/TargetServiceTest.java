package dev.nocs.target;

import java.time.Instant;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@TestPropertySource(properties = "nocs.auth.token=t")
class TargetServiceTest {

    @Autowired TargetService service;
    @Autowired JdbcTemplate jdbc;

    @BeforeEach
    void reset() {
        jdbc.update("DELETE FROM targets_custom");
        jdbc.update("DELETE FROM observatories");
        jdbc.update("INSERT INTO observatories(name, latitude_deg, longitude_deg, elevation_m, timezone, is_active) "
                + "VALUES('Test', 40.0, -74.0, 0, 'UTC', 1)");
    }

    @Test
    void searchFindsM31() {
        var hits = service.search("M31", 5);
        assertThat(hits).isNotEmpty();
        assertThat(hits.get(0).target().id()).isEqualTo("messier:M31");
        assertThat(hits.get(0).observation()).isPresent();
    }

    @Test
    void searchFindsAndromedaByAlias() {
        var hits = service.search("Andromeda", 5);
        assertThat(hits).extracting(r -> r.target().id()).contains("messier:M31");
    }

    @Test
    void searchFindsSun() {
        var hits = service.search("Sun", 5);
        assertThat(hits).extracting(r -> r.target().id()).contains("sun");
    }

    @Test
    void resolveByIdReturnsObservation() {
        Optional<TargetService.Resolved> r = service.resolveById("messier:M31", Instant.parse("2026-04-22T00:00:00Z"));
        assertThat(r).isPresent();
        assertThat(r.get().observation()).isPresent();
        TargetObservation obs = r.get().observation().get();
        assertThat(Double.isFinite(obs.altitudeDeg())).isTrue();
        assertThat(Double.isFinite(obs.azimuthDeg())).isTrue();
        assertThat(obs.transitUtc()).isPresent();
    }

    @Test
    void resolveCustomTargetWorks() {
        long id = service.addCustom("My Spot", 10.0, 20.0, "");
        var r = service.resolveById("custom:" + id, Instant.now());
        assertThat(r).isPresent();
        assertThat(r.get().target().primaryName()).isEqualTo("My Spot");
    }
}
