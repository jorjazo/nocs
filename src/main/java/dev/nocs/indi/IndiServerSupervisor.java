package dev.nocs.indi;

import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class IndiServerSupervisor {

    private static final Logger log = LoggerFactory.getLogger(IndiServerSupervisor.class);

    private final IndiConfig config;
    private final EventBus bus;
    private final AtomicBoolean started = new AtomicBoolean(false);

    private volatile Thread loop;
    private volatile Process current;
    private int consecutiveFailures;

    public IndiServerSupervisor(IndiConfig config, EventBus bus) {
        this.config = config;
        this.bus = bus;
    }

    public void start() {
        if (config.mode() != IndiConfig.Mode.MANAGED) {
            log.info("INDI supervisor disabled (mode={})", config.mode());
            return;
        }
        if (!started.compareAndSet(false, true)) {
            return;
        }
        consecutiveFailures = 0;
        loop = Thread.ofVirtual().name("indi-supervisor").start(this::runLoop);
    }

    public void stop() {
        if (!started.compareAndSet(true, false)) {
            return;
        }
        Process p = current;
        if (p != null && p.isAlive()) {
            p.destroy();
            try {
                if (!p.waitFor(5, java.util.concurrent.TimeUnit.SECONDS)) {
                    p.destroyForcibly();
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                p.destroyForcibly();
            }
        }
        if (loop != null) {
            try {
                loop.join(2000);
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
        }
    }

    public boolean isRunning() {
        Process p = current;
        return started.get() && p != null && p.isAlive();
    }

    protected ProcessBuilder buildProcess() {
        List<String> cmd = new ArrayList<>();
        cmd.add("indiserver");
        // Default abstract socket /tmp/indiserver conflicts with other indiserver instances; isolate by port.
        cmd.add("-u");
        cmd.add("/tmp/nocs-indiserver-" + config.port());
        cmd.add("-p");
        cmd.add(String.valueOf(config.port()));
        cmd.addAll(config.drivers());
        return new ProcessBuilder(cmd);
    }

    private void runLoop() {
        while (started.get()) {
            try {
                ProcessBuilder pb = buildProcess().redirectErrorStream(true);
                current = pb.start();
                bus.publish(Event.of(
                        Topic.SYSTEM,
                        "indiserver.up",
                        Map.of("pid", (long) current.pid(), "drivers", config.drivers())));
                pipeLogs(current);
                int code = current.waitFor();
                bus.publish(Event.of(Topic.SYSTEM, "indiserver.down", Map.of("exitCode", code)));
                if (!started.get()) {
                    break;
                }
                long backoff = Math.min(
                        config.restart().initialBackoffMs()
                                * (long) Math.pow(2, consecutiveFailures),
                        config.restart().maxBackoffMs());
                consecutiveFailures++;
                bus.publish(Event.of(
                        Topic.SYSTEM,
                        "indiserver.respawn",
                        Map.of("backoffMs", backoff, "consecutiveFailures", consecutiveFailures)));
                Thread.sleep(backoff);
            } catch (IOException e) {
                log.warn("indiserver start failed: {}", e.toString());
                try {
                    Thread.sleep(config.restart().initialBackoffMs());
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    return;
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return;
            }
        }
    }

    private void pipeLogs(Process p) {
        Thread.ofVirtual()
                .name("indi-log")
                .start(() -> {
                    try (BufferedReader r = new BufferedReader(
                            new InputStreamReader(p.getInputStream(), StandardCharsets.UTF_8))) {
                        String line;
                        while ((line = r.readLine()) != null) {
                            log.info("[indiserver] {}", line);
                        }
                    } catch (IOException e) {
                        log.debug("indiserver log pipe ended: {}", e.toString());
                    }
                });
    }
}
