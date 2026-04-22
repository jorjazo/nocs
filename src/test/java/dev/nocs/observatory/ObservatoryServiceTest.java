package dev.nocs.observatory;

import dev.nocs.astronomy.GeographicLocation;
import java.util.List;
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
class ObservatoryServiceTest {

    @Autowired ObservatoryService service;
    @Autowired JdbcTemplate jdbc;

    @BeforeEach
    void reset() {
        jdbc.update("DELETE FROM observatories");
    }

    @Test
    void createAndListRoundTrip() {
        Observatory created = service.create("Backyard", 40.0, -74.0, 50.0, "America/New_York", "[]");
        List<Observatory> all = service.list();
        assertThat(all).hasSize(1);
        assertThat(all.get(0).name()).isEqualTo("Backyard");
        assertThat(created.id()).isPositive();
    }

    @Test
    void firstCreatedBecomesActive() {
        Observatory a = service.create("Alpha", 40, -74, 50, "UTC", "[]");
        assertThat(service.active()).isPresent();
        assertThat(service.active().get().id()).isEqualTo(a.id());
    }

    @Test
    void activateSwapsTheActiveRow() {
        Observatory a = service.create("Alpha", 40, -74, 50, "UTC", "[]");
        Observatory b = service.create("Beta", 41, -74, 60, "UTC", "[]");
        assertThat(service.active().orElseThrow().id()).isEqualTo(a.id());
        service.activate(b.id());
        assertThat(service.active().orElseThrow().id()).isEqualTo(b.id());
    }

    @Test
    void deleteRemovesRow() {
        Observatory a = service.create("Alpha", 40, -74, 50, "UTC", "[]");
        service.delete(a.id());
        assertThat(service.list()).isEmpty();
        assertThat(service.active()).isEmpty();
    }

    @Test
    void activeLocationExposesGeographicLocation() {
        service.create("Alpha", 40.0, -74.0, 50.0, "UTC", "[]");
        Optional<GeographicLocation> loc = service.activeLocation();
        assertThat(loc).isPresent();
        assertThat(loc.get().latitudeDeg()).isEqualTo(40.0);
    }
}
