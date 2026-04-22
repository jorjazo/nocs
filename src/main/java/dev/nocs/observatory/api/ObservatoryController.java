package dev.nocs.observatory.api;

import dev.nocs.observatory.ObservatoryService;
import dev.nocs.observatory.api.dto.CreateObservatoryRequest;
import dev.nocs.observatory.api.dto.ObservatoryView;
import dev.nocs.observatory.api.dto.UpdateObservatoryRequest;
import java.util.List;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/observatories")
public class ObservatoryController {

    private final ObservatoryService service;

    public ObservatoryController(ObservatoryService service) {
        this.service = service;
    }

    @GetMapping
    public List<ObservatoryView> list() {
        return service.list().stream().map(ObservatoryView::of).toList();
    }

    @GetMapping("/{id}")
    public ResponseEntity<ObservatoryView> get(@PathVariable long id) {
        return service.find(id)
                .map(ObservatoryView::of)
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    @PostMapping
    public ObservatoryView create(@RequestBody CreateObservatoryRequest req) {
        return ObservatoryView.of(service.create(
                req.name(),
                req.latitudeDeg(),
                req.longitudeDeg(),
                req.elevationM(),
                req.timezone(),
                req.horizonMaskJson()));
    }

    @PatchMapping("/{id}")
    public ObservatoryView update(@PathVariable long id, @RequestBody UpdateObservatoryRequest req) {
        return ObservatoryView.of(service.update(
                id,
                req.name(),
                req.latitudeDeg(),
                req.longitudeDeg(),
                req.elevationM(),
                req.timezone(),
                req.horizonMaskJson()));
    }

    @PostMapping("/{id}/activate")
    public Map<String, Object> activate(@PathVariable long id) {
        service.activate(id);
        return Map.of("id", id, "active", true);
    }

    @DeleteMapping("/{id}")
    public Map<String, Object> delete(@PathVariable long id) {
        service.delete(id);
        return Map.of("id", id, "deleted", true);
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, String>> badRequest(IllegalArgumentException e) {
        return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
    }
}
