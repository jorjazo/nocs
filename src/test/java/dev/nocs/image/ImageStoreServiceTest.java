package dev.nocs.image;

import dev.nocs.device.DeviceId;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.MethodOrderer;
import org.junit.jupiter.api.Order;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestMethodOrder;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@TestPropertySource(properties = "nocs.auth.token=t")
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
class ImageStoreServiceTest {

    @Autowired
    ImageStoreService store;
    @Autowired
    ImageRepository repo;
    @Autowired
    EventBus bus;

    @Test
    @Order(1)
    void prepareThenStoreWritesFitsThumbAndRow() {
        DeviceId cam = new DeviceId("ccd-sim");
        store.prepareCapture(cam, new CaptureContext("L", "M31", 30.0, "L_30s", 1));

        CopyOnWriteArrayList<Map<String, Object>> saved = new CopyOnWriteArrayList<>();
        var sub = bus.subscribe(java.util.EnumSet.of(Topic.CAMERA))
                .filter(e -> "image_saved".equals(e.type()))
                .subscribe(e -> saved.add(e.payload()));

        short[] pixels = new short[8 * 8];
        for (int i = 0; i < pixels.length; i++) {
            pixels[i] = (short) (i * 100 - 32768);
        }
        byte[] fits = MiniFits.build16(8, 8, pixels, Map.of(
                "DATE-OBS", "'2026-04-22T22:00:00'"));

        store.accept(cam, fits, ".fits");

        Awaitility.await().atMost(Duration.ofSeconds(5)).untilAsserted(() -> {
            var forCam = saved.stream().filter(p -> "ccd-sim".equals(p.get("device"))).toList();
            assertThat(forCam).hasSize(1);
        });
        long id = ((Number) saved.stream()
                        .filter(p -> "ccd-sim".equals(p.get("device")))
                        .findFirst()
                        .orElseThrow()
                        .get("id"))
                .longValue();

        Awaitility.await().atMost(Duration.ofSeconds(5)).untilAsserted(() -> {
            ImageRecord rec = repo.findById(id).orElseThrow();
            assertThat(rec.filter()).isEqualTo("L");
            assertThat(rec.target()).isEqualTo("M31");
            assertThat(rec.fitsPath()).contains("L_30s_").endsWith(".fits");
            assertThat(Path.of(rec.fitsPath())).exists();
            assertThat(rec.thumbPath()).isNotNull();
            assertThat(Path.of(rec.thumbPath())).exists();
            assertThat(Files.size(Path.of(rec.fitsPath()))).isEqualTo(fits.length);
            assertThat(rec.bitpix()).isEqualTo(16);
            assertThat(rec.width()).isEqualTo(8);
            assertThat(rec.height()).isEqualTo(8);
            assertThat(rec.dateObs()).isEqualTo("2026-04-22T22:00:00");
        });
        sub.dispose();
    }

    @Test
    @Order(2)
    void usesDefaultsWhenNoCapturePrepared() {
        DeviceId cam = new DeviceId("ccd-other");
        byte[] fits = MiniFits.build16(4, 4, new short[16], null);

        store.accept(cam, fits, ".fits");

        Awaitility.await().atMost(Duration.ofSeconds(2)).untilAsserted(() -> {
            var rows = repo.list(new ImageRepository.Filters("ccd-other", null, null, null, 10, 0));
            assertThat(rows).isNotEmpty();
            ImageRecord rec = rows.get(0);
            assertThat(rec.filter()).isEqualTo("UNK");
            assertThat(rec.target()).isEqualTo("untargeted");
            assertThat(Path.of(rec.fitsPath())).exists();
        });
    }
}
