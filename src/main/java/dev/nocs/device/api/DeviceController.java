package dev.nocs.device.api;

import dev.nocs.device.Camera;
import dev.nocs.device.Device;
import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceService;
import dev.nocs.device.FilterWheel;
import dev.nocs.device.Focuser;
import dev.nocs.device.Mount;
import dev.nocs.device.api.dto.DeviceView;
import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/devices")
public class DeviceController {

    private final DeviceService service;

    public DeviceController(DeviceService service) {
        this.service = service;
    }

    @GetMapping
    public List<DeviceView> list() {
        return service.list().stream().map(DeviceController::view).toList();
    }

    @PostMapping("/{id}/connect")
    public void connect(@PathVariable String id) {
        service.connect(new DeviceId(id));
    }

    @PostMapping("/{id}/disconnect")
    public void disconnect(@PathVariable String id) {
        service.disconnect(new DeviceId(id));
    }

    private static DeviceView view(Device d) {
        String state =
                switch (d.kind()) {
                    case MOUNT -> ((Mount) d).state().name();
                    case CAMERA -> ((Camera) d).state().name();
                    case FILTERWHEEL -> ((FilterWheel) d).state().name();
                    case FOCUSER -> ((Focuser) d).state().name();
                    case UNKNOWN -> "UNKNOWN";
                };
        return new DeviceView(d.id().value(), d.indiName(), d.kind().name().toLowerCase(), state, d.isConnected());
    }
}
