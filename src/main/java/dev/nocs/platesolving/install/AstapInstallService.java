package dev.nocs.platesolving.install;

import dev.nocs.config.NocsProperties;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import jakarta.annotation.PreDestroy;
import java.nio.file.Path;
import java.time.Instant;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Function;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class AstapInstallService {

    private static final Logger log = LoggerFactory.getLogger(AstapInstallService.class);

    private final NocsProperties props;
    private final Path dataDir;
    private final EventBus bus;
    private final AstapInstaller installer;
    private final Function<NocsProperties, Optional<AstapInstallSpec>> specResolver;
    private final ExecutorService executor = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "astap-install");
        t.setDaemon(true);
        return t;
    });
    private final AtomicReference<InstallProgress> progress = new AtomicReference<>(InstallProgress.idle());
    private volatile boolean inFlight = false;

    public AstapInstallService(
            NocsProperties props,
            Path dataDir,
            EventBus bus,
            AstapInstaller installer,
            Function<NocsProperties, Optional<AstapInstallSpec>> specResolver) {
        this.props = props;
        this.dataDir = dataDir;
        this.bus = bus;
        this.installer = installer;
        this.specResolver = specResolver;
    }

    public synchronized void start(InstallRequest request) {
        if (request == null || !request.acceptLicense()) {
            throw new IllegalArgumentException("must accept ASTAP license to install");
        }
        if (props.platesolving() == null
                || props.platesolving().install() == null
                || !Boolean.TRUE.equals(props.platesolving().install().allowNetwork())) {
            throw new IllegalStateException(
                    "install blocked: set nocs.platesolving.install.allow-network=true to opt in");
        }
        if (inFlight) {
            throw new IllegalStateException("install already in progress");
        }
        Optional<AstapInstallSpec> spec = specResolver.apply(props);
        if (spec.isEmpty()) {
            throw new IllegalStateException(
                    "no install spec for current platform: " + AstapInstallSpecs.currentPlatformKey());
        }
        inFlight = true;
        publish("install_started", Map.of(
                "platform",
                AstapInstallSpecs.currentPlatformKey() == null
                        ? "unknown"
                        : AstapInstallSpecs.currentPlatformKey(),
                "binary_url", spec.get().binaryUrl().toString(),
                "db_url", spec.get().dbUrl().toString()));
        executor.submit(() -> runInstall(spec.get()));
    }

    private void runInstall(AstapInstallSpec spec) {
        try {
            updateProgress(InstallPhase.RESOLVING_SPEC, 0, 0, "resolving install spec");
            installer.install(spec, dataDir, new AstapInstaller.InstallEvents() {
                @Override
                public void phase(InstallPhase phase, String message) {
                    updateProgress(phase, progress.get().bytesDone(), progress.get().bytesTotal(), message);
                }

                @Override
                public void bytes(InstallPhase phase, long done, long total) {
                    updateProgress(phase, done, total, progress.get().message());
                }
            });
            updateProgress(
                    InstallPhase.DONE, progress.get().bytesDone(), progress.get().bytesTotal(), "install complete");
            publish("install_completed", Map.of("phase", InstallPhase.DONE.name().toLowerCase()));
        } catch (Exception e) {
            log.error("ASTAP install failed", e);
            updateProgress(
                    InstallPhase.FAILED,
                    progress.get().bytesDone(),
                    progress.get().bytesTotal(),
                    e.getMessage() == null ? "install failed" : e.getMessage());
            publish("install_failed", Map.of(
                    "error", e.getMessage() == null ? "install failed" : e.getMessage()));
        } finally {
            inFlight = false;
        }
    }

    public InstallProgress progress() {
        return progress.get();
    }

    public boolean isInFlight() {
        return inFlight;
    }

    private void updateProgress(InstallPhase phase, long done, long total, String msg) {
        InstallProgress p = new InstallProgress(phase, done, total, msg, Instant.now());
        progress.set(p);
        Map<String, Object> payload = new HashMap<>();
        payload.put("phase", phase.name().toLowerCase());
        payload.put("bytes_done", done);
        payload.put("bytes_total", total);
        payload.put("message", msg);
        bus.publish(Event.of(Topic.PLATESOLVING, "install_progress", payload));
    }

    private void publish(String type, Map<String, Object> payload) {
        bus.publish(Event.of(Topic.PLATESOLVING, type, payload));
    }

    @PreDestroy
    public void shutdown() {
        executor.shutdownNow();
    }
}
