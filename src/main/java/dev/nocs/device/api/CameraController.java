package dev.nocs.device.api;

import dev.nocs.device.Camera;
import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceService;
import dev.nocs.device.api.dto.CoolRequest;
import dev.nocs.device.api.dto.ExposeRequest;
import dev.nocs.image.CaptureContext;
import dev.nocs.image.ImageStoreService;
import java.util.NoSuchElementException;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/cameras/{id}")
public class CameraController {

    private final DeviceService service;
    private final ImageStoreService imageStore;

    public CameraController(DeviceService service, ImageStoreService imageStore) {
        this.service = service;
        this.imageStore = imageStore;
    }

    @PostMapping("/expose")
    public void expose(@PathVariable String id, @RequestBody ExposeRequest req) {
        DeviceId deviceId = new DeviceId(id);
        CaptureContext ctx = new CaptureContext(
                req.filter(),
                req.target(),
                req.durationSeconds(),
                req.step(),
                req.seq() == null ? 0 : req.seq());
        imageStore.prepareCapture(deviceId, ctx);
        camera(id).expose(req.durationSeconds());
    }

    @PostMapping("/cool")
    public void cool(@PathVariable String id, @RequestBody CoolRequest req) {
        camera(id).cool(req.setpointCelsius());
    }

    private Camera camera(String id) {
        return service.registry()
                .camera(new DeviceId(id))
                .orElseThrow(() -> new NoSuchElementException("no camera: " + id));
    }
}
