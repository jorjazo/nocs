package dev.nocs.image;

import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@TestPropertySource(properties = "nocs.auth.token=t")
class ImageRepositoryTest {

    @Autowired
    ImageRepository repo;

    @Test
    void insertAndFind() {
        ImageRecord rec = ImageRecord.forInsert(
                null, "ccd-sim",
                new CaptureContext("L", "m31", 120.0, "L_120s", 1),
                "/tmp/m31/L_120s_001.fits", "/tmp/m31/L_120s_001.thumb.jpg",
                4096L, 60, 60, 16, "2026-04-22T22:00:00");

        long id = repo.insert(rec);
        Optional<ImageRecord> found = repo.findById(id);

        assertThat(found).isPresent();
        assertThat(found.get().id()).isEqualTo(id);
        assertThat(found.get().filter()).isEqualTo("L");
        assertThat(found.get().bytes()).isEqualTo(4096L);
        assertThat(found.get().createdAt()).isNotNull();
    }

    @Test
    void listFiltersByDevice() {
        long aId = repo.insert(ImageRecord.forInsert(
                null, "ccd-a", new CaptureContext("L", "m31", 1, "", 1),
                "/tmp/a.fits", null, 1, 1, 1, 16, null));
        long bId = repo.insert(ImageRecord.forInsert(
                null, "ccd-b", new CaptureContext("L", "m31", 1, "", 1),
                "/tmp/b.fits", null, 1, 1, 1, 16, null));

        List<ImageRecord> onlyA = repo.list(new ImageRepository.Filters("ccd-a", null, null, null, 100, 0));
        assertThat(onlyA).extracting(ImageRecord::id).contains(aId).doesNotContain(bId);
    }

    @Test
    void deleteRemovesRow() {
        long id = repo.insert(ImageRecord.forInsert(
                null, "ccd-sim", new CaptureContext("L", "m31", 1, "", 1),
                "/tmp/x.fits", null, 1, 1, 1, 16, null));
        boolean removed = repo.delete(id);
        assertThat(removed).isTrue();
        assertThat(repo.findById(id)).isEmpty();
    }
}
