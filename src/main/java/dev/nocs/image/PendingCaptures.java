package dev.nocs.image;

import dev.nocs.device.DeviceId;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

public class PendingCaptures {

    private final Map<DeviceId, CaptureContext> pending = new ConcurrentHashMap<>();

    public void prepare(DeviceId camera, CaptureContext ctx) {
        pending.put(camera, ctx);
    }

    public Optional<CaptureContext> consume(DeviceId camera) {
        return Optional.ofNullable(pending.remove(camera));
    }
}
