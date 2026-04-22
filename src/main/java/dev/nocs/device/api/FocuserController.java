package dev.nocs.device.api;

import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceService;
import dev.nocs.device.Focuser;
import dev.nocs.device.api.dto.MoveRequest;
import java.util.NoSuchElementException;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/focusers/{id}")
public class FocuserController {

    private final DeviceService service;

    public FocuserController(DeviceService service) {
        this.service = service;
    }

    @PostMapping("/move")
    public void move(@PathVariable String id, @RequestBody MoveRequest req) {
        if (req.position() != null) {
            focuser(id).moveAbsolute(req.position());
        } else if (req.offset() != null) {
            focuser(id).moveRelative(req.offset());
        } else {
            throw new IllegalArgumentException("supply either position or offset");
        }
    }

    private Focuser focuser(String id) {
        return service.registry()
                .focuser(new DeviceId(id))
                .orElseThrow(() -> new NoSuchElementException("no focuser: " + id));
    }
}
