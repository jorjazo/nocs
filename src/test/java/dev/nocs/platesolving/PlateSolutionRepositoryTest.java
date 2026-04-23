package dev.nocs.platesolving;

import java.time.Instant;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@TestPropertySource(properties = "nocs.auth.token=t")
class PlateSolutionRepositoryTest {

    @Autowired PlateSolutionRepository repo;
    @Autowired JdbcTemplate jdbc;

    @Test
    void upsertInsertsAndReplaces() {
        long imageId = createImage("dev1", "L_30s_001.fits");

        repo.upsert(PlateSolutionRecord.forInsert(
                imageId, 1.0, 2.0, 1.5, 12.0, 0.5, 0.4, 200L, "astap", Instant.now()));
        Optional<PlateSolutionRecord> first = repo.findByImageId(imageId);
        assertThat(first).isPresent();
        assertThat(first.get().raJ2000Deg()).isEqualTo(1.0);

        repo.upsert(PlateSolutionRecord.forInsert(
                imageId, 9.9, 8.8, 1.5, 12.0, 0.5, 0.4, 250L, "astap", Instant.now()));

        Optional<PlateSolutionRecord> second = repo.findByImageId(imageId);
        assertThat(second).isPresent();
        assertThat(second.get().raJ2000Deg()).isEqualTo(9.9);
        assertThat(second.get().decJ2000Deg()).isEqualTo(8.8);
    }

    @Test
    void deleteRemovesRow() {
        long imageId = createImage("dev1", "L_30s_002.fits");
        repo.upsert(PlateSolutionRecord.forInsert(
                imageId, 5.0, 5.0, 1.0, 0.0, 0.5, 0.4, 100L, "astap", Instant.now()));

        boolean removed = repo.deleteByImageId(imageId);

        assertThat(removed).isTrue();
        assertThat(repo.findByImageId(imageId)).isEmpty();
    }

    private long createImage(String device, String fileName) {
        jdbc.update("INSERT INTO images(device_id, fits_path, bytes) VALUES(?,?,0)", device, "/tmp/" + fileName);
        return jdbc.queryForObject(
                "SELECT id FROM images WHERE fits_path = ?", Long.class, "/tmp/" + fileName);
    }
}
