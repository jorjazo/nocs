package dev.nocs.device.api;

import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceService;
import dev.nocs.device.FilterWheel;
import dev.nocs.device.api.dto.SelectSlotRequest;
import java.util.NoSuchElementException;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/filterwheels/{id}")
public class FilterWheelController {

    private final DeviceService service;

    public FilterWheelController(DeviceService service) {
        this.service = service;
    }

    @PostMapping("/select")
    public void select(@PathVariable String id, @RequestBody SelectSlotRequest req) {
        wheel(id).selectSlot(req.slot());
    }

    private FilterWheel wheel(String id) {
        return service.registry()
                .filterWheel(new DeviceId(id))
                .orElseThrow(() -> new NoSuchElementException("no filter wheel: " + id));
    }
}
