package dev.nocs.device.api;

import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceService;
import dev.nocs.device.Mount;
import dev.nocs.device.api.dto.SlewRequest;
import java.util.NoSuchElementException;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/mounts/{id}")
public class MountController {

    private final DeviceService service;

    public MountController(DeviceService service) {
        this.service = service;
    }

    @PostMapping("/slew")
    public void slew(@PathVariable String id, @RequestBody SlewRequest req) {
        mount(id).slew(req.raHours(), req.decDegrees());
    }

    @PostMapping("/park")
    public void park(@PathVariable String id) {
        mount(id).park();
    }

    @PostMapping("/sync")
    public void sync(@PathVariable String id, @RequestBody SlewRequest req) {
        mount(id).syncTo(req.raHours(), req.decDegrees());
    }

    private Mount mount(String id) {
        return service.registry()
                .mount(new DeviceId(id))
                .orElseThrow(() -> new NoSuchElementException("no mount: " + id));
    }
}
