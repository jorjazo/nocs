package dev.nocs.safety.api;

import dev.nocs.safety.ActiveTarget;
import dev.nocs.safety.SafetyRule;
import dev.nocs.safety.SafetyService;
import dev.nocs.safety.SensorReading;
import dev.nocs.safety.api.dto.ActiveTargetRequest;
import dev.nocs.safety.api.dto.EStopRequest;
import dev.nocs.safety.api.dto.RuleView;
import dev.nocs.safety.api.dto.SafetyStatusView;
import dev.nocs.safety.api.dto.SensorReadingRequest;
import jakarta.servlet.http.HttpServletRequest;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/safety")
public class SafetyController {

    private final SafetyService service;

    public SafetyController(SafetyService service) {
        this.service = service;
    }

    @GetMapping("/rules")
    public SafetyStatusView rules() {
        List<SafetyRule> loaded = service.rules();
        List<RuleView> views = loaded.stream()
                .map(r -> RuleView.of(r, service.stateSnapshot().isLatched(r.name())))
                .toList();
        return new SafetyStatusView(
                views,
                List.copyOf(service.stateSnapshot().latchedRules()),
                service.stateSnapshot()
                        .activeTarget()
                        .map(ActiveTarget::targetId)
                        .orElse(null));
    }

    @PostMapping("/rules/reload")
    public Map<String, Object> reload() {
        service.reload();
        return Map.of("rules", service.rules().size());
    }

    @PostMapping("/e-stop")
    public Map<String, String> eStop(
            @RequestBody(required = false) EStopRequest req, HttpServletRequest http) {
        String reason = req == null || req.reason() == null ? "manual" : req.reason();
        service.eStop(reason, callerOf(http));
        return Map.of("status", "ok");
    }

    @PostMapping("/reset")
    public Map<String, String> reset(HttpServletRequest http) {
        service.reset(callerOf(http));
        return Map.of("status", "ok");
    }

    @PostMapping("/sensors/readings")
    public Map<String, String> reading(
            @RequestBody SensorReadingRequest req, HttpServletRequest http) {
        if (req == null || req.sensor() == null || req.sensor().isBlank()) {
            throw new IllegalArgumentException("sensor is required");
        }
        Instant ts = req.ts() == null ? Instant.now() : req.ts();
        service.postReading(new SensorReading(req.sensor(), ts, req.values()), callerOf(http));
        return Map.of("status", "ok");
    }

    @PostMapping("/active-target")
    public Map<String, String> activeTarget(
            @RequestBody ActiveTargetRequest req, HttpServletRequest http) {
        if (req == null || req.targetId() == null || req.targetId().isBlank()) {
            throw new IllegalArgumentException("targetId is required");
        }
        service.setActiveTarget(
                new ActiveTarget(req.targetId(), req.raJ2000Deg(), req.decJ2000Deg(), Instant.now()), callerOf(http));
        return Map.of("status", "ok");
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, String>> badRequest(IllegalArgumentException e) {
        return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
    }

    private static String callerOf(HttpServletRequest http) {
        String addr = http.getRemoteAddr();
        String ua = http.getHeader("User-Agent");
        if (addr == null && ua == null) {
            return "unknown";
        }
        return (addr == null ? "?" : addr) + (ua == null ? "" : " (" + ua + ")");
    }
}
