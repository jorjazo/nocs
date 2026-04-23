package dev.nocs.image;

import dev.nocs.platesolving.PlateSolution;
import dev.nocs.platesolving.PlateSolutionRepository;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.Map;
import java.util.Optional;
import java.util.SequencedMap;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@TestPropertySource(properties = "nocs.auth.token=t")
class ImageStoreServiceAmendHeaderTest {

    @Autowired ImageStoreService store;
    @Autowired PlateSolutionRepository solutions;

    @Test
    void amendHeaderReplacesFitsAndUpsertsPlateSolution() throws Exception {
        byte[] fits = MiniFits.build16(8, 8, new short[64], Map.of(
                "DATE-OBS", "'2026-04-22T22:00:00'"));
        store.prepareCapture(new dev.nocs.device.DeviceId("ccd-amend"), CaptureContext.defaults(60.0));
        store.accept(new dev.nocs.device.DeviceId("ccd-amend"), fits, ".fits");

        long imageId = store.list(new ImageRepository.Filters("ccd-amend", null, null, null, 10, 0))
                .get(0)
                .id();

        PlateSolution s = new PlateSolution(
                10.6847083, 41.269083, 1.234, 12.5, 0.5, 0.4, Instant.now(), "astap");
        SequencedMap<String, String> cards = s.toFitsCards();

        store.amendHeader(imageId, cards);

        ImageRecord rec = store.find(imageId).orElseThrow();
        byte[] reread = Files.readAllBytes(Path.of(rec.fitsPath()));
        FitsHeaderReader.Header h = FitsHeaderReader.read(reread);
        assertThat(reread.length % 2880).isZero();
        assertThat(rec.bytes()).isEqualTo(reread.length);
        String headerText = new String(reread, 0, h.dataOffset(), java.nio.charset.StandardCharsets.US_ASCII);
        assertThat(headerText).contains("CRVAL1");
        assertThat(headerText).contains("CRVAL2");

        Optional<dev.nocs.platesolving.PlateSolutionRecord> row = solutions.findByImageId(imageId);
        assertThat(row).isPresent();
        assertThat(row.get().raJ2000Deg()).isEqualTo(10.6847083);
        assertThat(row.get().solver()).isEqualTo("astap");
    }
}
