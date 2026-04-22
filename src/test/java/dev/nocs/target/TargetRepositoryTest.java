package dev.nocs.target;

import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@TestPropertySource(properties = "nocs.auth.token=t")
class TargetRepositoryTest {

    @Autowired TargetRepository repo;
    @Autowired JdbcTemplate jdbc;

    @BeforeEach
    void reset() {
        jdbc.update("DELETE FROM targets_custom");
    }

    @Test
    void insertAndListRoundTrip() {
        long id = repo.insert("My Dark Spot", 10.0, 20.0, TargetKind.CUSTOM, "behind my neighbour's oak");
        List<Target> all = repo.findAll();
        assertThat(all).hasSize(1);
        Target t = all.get(0);
        assertThat(t.id()).isEqualTo("custom:" + id);
        assertThat(t.primaryName()).isEqualTo("My Dark Spot");
        assertThat(t.raJ2000Deg()).isEqualTo(10.0);
    }

    @Test
    void deleteRemoves() {
        long id = repo.insert("X", 0, 0, TargetKind.CUSTOM, "");
        assertThat(repo.delete(id)).isTrue();
        assertThat(repo.delete(id)).isFalse();
        assertThat(repo.findAll()).isEmpty();
    }
}
