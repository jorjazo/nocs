package dev.nocs.target.api;

import dev.nocs.target.TargetService;
import dev.nocs.target.api.dto.CreateCustomTargetRequest;
import dev.nocs.target.api.dto.TargetSearchResult;
import dev.nocs.target.api.dto.TargetView;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/targets")
public class TargetController {

    private final TargetService service;

    public TargetController(TargetService service) {
        this.service = service;
    }

    @GetMapping("/search")
    public List<TargetSearchResult> search(
            @RequestParam("q") String q,
            @RequestParam(value = "limit", required = false, defaultValue = "20") int limit) {
        return service.search(q, limit).stream()
                .map(r -> new TargetSearchResult(TargetView.of(r.target()), r.observation().orElse(null)))
                .toList();
    }

    @GetMapping("/{id}")
    public ResponseEntity<TargetSearchResult> get(@PathVariable String id) {
        return service.resolveById(id, Instant.now())
                .map(r -> new TargetSearchResult(TargetView.of(r.target()), r.observation().orElse(null)))
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    @PostMapping("/custom")
    public Map<String, Object> addCustom(@RequestBody CreateCustomTargetRequest req) {
        long id = service.addCustom(req.name(), req.raJ2000Deg(), req.decJ2000Deg(), req.notes());
        return Map.of("id", id, "targetId", "custom:" + id);
    }

    @DeleteMapping("/custom/{id}")
    public ResponseEntity<Map<String, Object>> deleteCustom(@PathVariable long id) {
        boolean removed = service.deleteCustom(id);
        return removed
                ? ResponseEntity.ok(Map.of("id", id, "deleted", true))
                : ResponseEntity.notFound().build();
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, String>> badRequest(IllegalArgumentException e) {
        return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
    }
}
