package dev.nocs.indi;

import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.DisabledOnOs;
import org.junit.jupiter.api.condition.OS;

import static org.assertj.core.api.Assertions.assertThat;

@DisabledOnOs(OS.WINDOWS)
class IndiServerSupervisorTest {

    @Test
    void respawnsAfterFailureWithBackoff() throws Exception {
        EventBus bus = new EventBus();
        CopyOnWriteArrayList<String> events = new CopyOnWriteArrayList<>();
        var sub = bus.subscribe(java.util.EnumSet.of(Topic.SYSTEM)).subscribe(e -> events.add(e.type()));

        IndiConfig cfg = new IndiConfig(
                IndiConfig.Mode.MANAGED,
                "127.0.0.1",
                7624,
                List.of("stub"),
                new IndiConfig.Restart(50L, 500L));

        IndiServerSupervisor sup =
                new IndiServerSupervisor(cfg, bus) {
                    @Override
                    protected ProcessBuilder buildProcess() {
                        return new ProcessBuilder("/bin/sh", "-c", "echo starting; exit 1");
                    }
                };

        sup.start();

        Awaitility.await().atMost(Duration.ofSeconds(4))
                .untilAsserted(() -> assertThat(events).filteredOn(e -> e.equals("indiserver.down"))
                        .hasSizeGreaterThanOrEqualTo(2));

        sup.stop();
        sub.dispose();
    }

    @Test
    void stopTerminatesRunningProcess() throws Exception {
        EventBus bus = new EventBus();
        IndiConfig cfg = new IndiConfig(
                IndiConfig.Mode.MANAGED,
                "127.0.0.1",
                7624,
                List.of("stub"),
                new IndiConfig.Restart(500L, 2000L));

        IndiServerSupervisor sup =
                new IndiServerSupervisor(cfg, bus) {
                    @Override
                    protected ProcessBuilder buildProcess() {
                        return new ProcessBuilder(
                                "/bin/sh", "-c", "trap 'exit 0' TERM; while :; do sleep 0.1; done");
                    }
                };

        sup.start();
        Awaitility.await().atMost(Duration.ofSeconds(2)).until(sup::isRunning);
        sup.stop();
        assertThat(sup.isRunning()).isFalse();
    }
}
