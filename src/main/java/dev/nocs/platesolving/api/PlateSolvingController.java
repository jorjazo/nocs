package dev.nocs.platesolving.api;

import dev.nocs.config.NocsProperties;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.image.ImageStoreService;
import dev.nocs.platesolving.PlateSolvingService;
import dev.nocs.platesolving.SolveOptions;
import dev.nocs.platesolving.SolveOutcome;
import dev.nocs.platesolving.api.dto.InstallProgressView;
import dev.nocs.platesolving.api.dto.InstallStatusView;
import dev.nocs.platesolving.api.dto.PlateSolutionView;
import dev.nocs.platesolving.api.dto.SolveRequest;
import dev.nocs.platesolving.api.dto.SolveResponse;
import dev.nocs.platesolving.astap.AstapInstallation;
import dev.nocs.platesolving.astap.AstapInstallationLocator;
import dev.nocs.platesolving.install.AstapInstallService;
import dev.nocs.platesolving.install.AstapInstallSpecs;
import dev.nocs.platesolving.install.InstallRequest;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/platesolving")
public class PlateSolvingController {

    private final PlateSolvingService solver;
    private final ImageStoreService images;
    private final EventBus bus;
    private final NocsProperties props;
    private final Path dataDir;
    private final AstapInstallationLocator locator;
    private final AstapInstallService installService;

    public PlateSolvingController(
            PlateSolvingService solver,
            ImageStoreService images,
            EventBus bus,
            NocsProperties props,
            Path dataDir,
            AstapInstallationLocator locator,
            AstapInstallService installService) {
        this.solver = solver;
        this.images = images;
        this.bus = bus;
        this.props = props;
        this.dataDir = dataDir;
        this.locator = locator;
        this.installService = installService;
    }

    @PostMapping("/solve")
    public ResponseEntity<SolveResponse> solve(@RequestBody SolveRequest req) {
        if (req == null || req.imageId() == null) {
            return ResponseEntity.badRequest()
                    .body(SolveResponse.failure(0L, "VALIDATION", "image_id required", 0L));
        }
        long id = req.imageId();
        Optional<byte[]> bytes = images.loadFits(id);
        if (bytes.isEmpty()) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND)
                    .body(SolveResponse.failure(id, "NOT_FOUND", "image not found", 0L));
        }
        SolveOptions opts = new SolveOptions(
                req.raHintHours() == null ? null : req.raHintHours() * 15.0,
                req.decHintDeg(),
                req.radiusDeg(),
                req.scaleHintArcsecPerPx(),
                req.timeoutSec());
        bus.publish(Event.of(Topic.PLATESOLVING, "solve_started", Map.of("image_id", id)));
        SolveOutcome outcome = solver.solve(bytes.get(), opts);
        if (outcome instanceof SolveOutcome.Solved s) {
            images.amendHeader(id, s.solution().toFitsCards());
            PlateSolutionView view = PlateSolutionView.from(s.solution(), s.durationMs());
            Map<String, Object> payload = new HashMap<>();
            payload.put("image_id", id);
            payload.put("ra_j2000_deg", s.solution().raJ2000Deg());
            payload.put("dec_j2000_deg", s.solution().decJ2000Deg());
            payload.put("solver", s.solution().solver());
            payload.put("duration_ms", s.durationMs());
            bus.publish(Event.of(Topic.PLATESOLVING, "solved", payload));
            return ResponseEntity.ok(SolveResponse.success(id, view));
        }
        SolveOutcome.Failed f = (SolveOutcome.Failed) outcome;
        bus.publish(Event.of(Topic.PLATESOLVING, "solve_failed", Map.of(
                "image_id", id,
                "failure_kind", f.kind().wire(),
                "message", f.message(),
                "duration_ms", f.durationMs())));
        return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY)
                .body(SolveResponse.failure(id, f.kind().wire(), f.message(), f.durationMs()));
    }

    @GetMapping("/install")
    public InstallStatusView installStatus() {
        Optional<AstapInstallation> inst = locator.locate(props, dataDir);
        boolean supported = AstapInstallSpecs.currentPlatformKey() != null;
        boolean allow = props.platesolving() != null
                && props.platesolving().install() != null
                && Boolean.TRUE.equals(props.platesolving().install().allowNetwork());
        if (inst.isPresent()) {
            return new InstallStatusView(
                    true,
                    inst.get().binary().toString(),
                    inst.get().dbDir().toString(),
                    inst.get().dbName(),
                    true,
                    supported,
                    allow);
        }
        String dbName = props.platesolving() == null || props.platesolving().astap() == null
                ? "H18"
                : props.platesolving().astap().dbName();
        return new InstallStatusView(false, null, null, dbName, false, supported, allow);
    }

    @PostMapping("/install")
    public ResponseEntity<?> startInstall(@RequestBody(required = false) InstallRequest body) {
        InstallRequest req = body == null ? new InstallRequest(false) : body;
        try {
            installService.start(req);
            return ResponseEntity.accepted().build();
        } catch (IllegalArgumentException e) {
            return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(Map.of("error", e.getMessage()));
        } catch (IllegalStateException e) {
            String msg = e.getMessage() == null ? "" : e.getMessage();
            HttpStatus status = msg.contains("already")
                    ? HttpStatus.CONFLICT
                    : msg.contains("allow-network") ? HttpStatus.FORBIDDEN
                            : HttpStatus.NOT_IMPLEMENTED;
            return ResponseEntity.status(status).body(Map.of("error", msg));
        }
    }

    @GetMapping("/install/progress")
    public InstallProgressView installProgress() {
        return InstallProgressView.from(installService.progress());
    }
}
