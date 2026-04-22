package dev.nocs.device;

import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

public class TempDirCameraImageSink implements CameraImageSink {

    private final Path tempRoot;
    private final EventBus bus;
    private final AtomicLong seq = new AtomicLong();

    public TempDirCameraImageSink(Path dataDir, EventBus bus) {
        this.tempRoot = dataDir.resolve("captures").resolve("tmp");
        this.bus = bus;
    }

    @Override
    public void accept(DeviceId camera, byte[] bytes, String extension) {
        try {
            Files.createDirectories(tempRoot);
            String ext = (extension == null || extension.isBlank())
                    ? ".bin"
                    : (extension.startsWith(".") ? extension : "." + extension);
            Path target = tempRoot.resolve(Instant.now().toEpochMilli() + "-" + seq.incrementAndGet() + ext);
            Files.write(target, bytes);
            bus.publish(Event.of(
                    Topic.CAMERA,
                    "image_received",
                    Map.of(
                            "device", camera.value(),
                            "path", target.toString(),
                            "bytes", bytes.length,
                            "extension", ext)));
        } catch (IOException e) {
            throw new RuntimeException("failed to write captured BLOB for " + camera.value(), e);
        }
    }
}
