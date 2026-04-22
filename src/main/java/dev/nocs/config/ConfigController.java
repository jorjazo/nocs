package dev.nocs.config;

import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/config")
public class ConfigController {

    private final ConfigService service;

    public ConfigController(ConfigService service) {
        this.service = service;
    }

    @GetMapping
    public Map<String, String> getAll() {
        return service.getAll();
    }

    @PatchMapping
    public ResponseEntity<Map<String, String>> patch(@RequestBody Map<String, String> body) {
        service.updateAll(body);
        return ResponseEntity.ok(service.getAll());
    }
}
