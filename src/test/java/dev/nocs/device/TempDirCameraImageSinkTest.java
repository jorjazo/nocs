package dev.nocs.device;

import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import reactor.core.Disposable;

import static org.assertj.core.api.Assertions.assertThat;

class TempDirCameraImageSinkTest {

    @Test
    void writesBlobAndPublishesEvent(@TempDir Path tempRoot) {
        EventBus bus = new EventBus();
        CopyOnWriteArrayList<Map<String, Object>> seen = new CopyOnWriteArrayList<>();
        Disposable sub = bus.subscribe(java.util.EnumSet.of(Topic.CAMERA))
                .filter(e -> "image_received".equals(e.type()))
                .subscribe(e -> seen.add(e.payload()));

        TempDirCameraImageSink sink = new TempDirCameraImageSink(tempRoot, bus);
        sink.accept(new DeviceId("ccd-simulator"), new byte[] {1, 2, 3, 4}, ".fits");

        Awaitility.await().atMost(Duration.ofSeconds(2)).untilAsserted(() -> {
            assertThat(seen).hasSize(1);
            Path p = Path.of((String) seen.getFirst().get("path"));
            assertThat(Files.exists(p)).isTrue();
            assertThat(Files.readAllBytes(p)).containsExactly(1, 2, 3, 4);
            assertThat(p.getParent().getFileName().toString()).isEqualTo("tmp");
        });
        sub.dispose();
    }
}
