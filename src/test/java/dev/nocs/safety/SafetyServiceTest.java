package dev.nocs.safety;

import dev.nocs.astronomy.GeographicLocation;
import dev.nocs.device.DeviceRegistry;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.observatory.Observatory;
import dev.nocs.observatory.ObservatoryService;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.CopyOnWriteArrayList;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class SafetyServiceTest {

    @Test
    void postReadingTriggersMatchingRule(@TempDir Path tmp) throws Exception {
        Path rules = tmp.resolve("safety.yaml");
        Files.writeString(
                rules,
                """
                rules:
                  - name: rain
                    when: { rain_detected: true }
                    then: e_stop
                """);

        EventBus bus = new EventBus();
        RecordingDispatcher dispatcher = new RecordingDispatcher(bus);
        SafetyService svc = newService(bus, dispatcher, rules);
        svc.reload();

        svc.postReading(
                new SensorReading("weather", Instant.now(), Map.of("rain_detected", true)), "test");

        assertThat(dispatcher.triggered).hasSize(1);
        assertThat(dispatcher.triggered.get(0).rule().name()).isEqualTo("rain");
    }

    @Test
    void readingsArrivingViaBusAreEvaluated(@TempDir Path tmp) throws Exception {
        Path rules = tmp.resolve("safety.yaml");
        Files.writeString(
                rules,
                """
                rules:
                  - name: hum
                    when: { humidity_above: 90 }
                    then: pause_sequence
                """);

        EventBus bus = new EventBus();
        RecordingDispatcher dispatcher = new RecordingDispatcher(bus);
        SafetyService svc = newService(bus, dispatcher, rules);
        svc.reload();
        svc.start();
        try {
            bus.publish(
                    Event.of(Topic.SENSOR, "reading", Map.of("sensor", "weather", "ts", "2026-04-22T10:00:00Z", "values", Map.of("humidity", 95.0))));

            Awaitility.await().atMost(java.time.Duration.ofSeconds(5)).untilAsserted(() -> assertThat(dispatcher.triggered).hasSize(1));
        } finally {
            svc.stop();
        }
    }

    @Test
    void eStopBypassesRulesAndCallsDispatcher(@TempDir Path tmp) throws Exception {
        Path rules = tmp.resolve("safety.yaml");
        Files.writeString(rules, "rules: []\n");

        EventBus bus = new EventBus();
        RecordingDispatcher dispatcher = new RecordingDispatcher(bus);
        SafetyService svc = newService(bus, dispatcher, rules);
        svc.reload();

        svc.eStop("manual", "client-1");

        assertThat(dispatcher.eStopReasons).containsExactly("manual");
        assertThat(dispatcher.eStopCallers).containsExactly("client-1");
    }

    @Test
    void reloadFromMissingFileGivesEmptyRulesList(@TempDir Path tmp) {
        EventBus bus = new EventBus();
        RecordingDispatcher dispatcher = new RecordingDispatcher(bus);
        Path rules = tmp.resolve("nope.yaml");
        SafetyService svc = newService(bus, dispatcher, rules);

        svc.reload();
        assertThat(svc.rules()).isEmpty();
    }

    @Test
    void invalidYamlReloadKeepsExistingRules(@TempDir Path tmp) throws Exception {
        Path rules = tmp.resolve("safety.yaml");
        Files.writeString(
                rules,
                """
                rules:
                  - name: rain
                    when: { rain_detected: true }
                    then: e_stop
                """);

        EventBus bus = new EventBus();
        SafetyService svc = newService(bus, new RecordingDispatcher(bus), rules);
        svc.reload();
        assertThat(svc.rules()).hasSize(1);

        Files.writeString(rules, "rules:\n  - name: x\n    then: nuke_everything\n");
        assertThatThrownBy(svc::reload).isInstanceOfAny(IllegalArgumentException.class, IllegalStateException.class);
        assertThat(svc.rules()).hasSize(1);
    }

    @Test
    void altitudeEvaluatorTriggersAltitudeBelowRule(@TempDir Path tmp) throws Exception {
        Path rules = tmp.resolve("safety.yaml");
        Files.writeString(
                rules,
                """
                rules:
                  - name: low
                    when: { altitude_below: 30 }
                    then: abort_and_park
                """);

        EventBus bus = new EventBus();
        RecordingDispatcher dispatcher = new RecordingDispatcher(bus);
        ObservatoryService obs = mock(ObservatoryService.class);
        when(obs.activeLocation()).thenReturn(Optional.of(new GeographicLocation(45.0, 0.0, 0.0)));
        when(obs.active())
                .thenReturn(Optional.of(new Observatory(1, "Test", 45.0, 0.0, 0.0, "UTC", "[]", true)));

        SafetyService svc = new SafetyService(
                bus,
                dispatcher,
                new SafetyRuleEngine(),
                new SafetyState(),
                new SafetyRuleParser(),
                obs,
                rules,
                60_000L,
                60L);
        svc.reload();
        svc.setActiveTarget(new ActiveTarget("synthetic:south", 0.0, -89.9, Instant.now()), "test");
        svc.evaluateAltitudeNow();

        assertThat(dispatcher.triggered).extracting(t -> t.rule().name()).contains("low");
    }

    private SafetyService newService(EventBus bus, RecordingDispatcher dispatcher, Path rulesPath) {
        ObservatoryService obs = mock(ObservatoryService.class);
        when(obs.activeLocation()).thenReturn(Optional.empty());
        return new SafetyService(
                bus, dispatcher, new SafetyRuleEngine(), new SafetyState(), new SafetyRuleParser(), obs, rulesPath, 60_000L, 60L);
    }

    static final class RecordingDispatcher extends SafetyActionDispatcher {
        final CopyOnWriteArrayList<TriggeredRule> triggered = new CopyOnWriteArrayList<>();
        final CopyOnWriteArrayList<String> eStopReasons = new CopyOnWriteArrayList<>();
        final CopyOnWriteArrayList<String> eStopCallers = new CopyOnWriteArrayList<>();
        final CopyOnWriteArrayList<String> resetCallers = new CopyOnWriteArrayList<>();

        RecordingDispatcher(EventBus bus) {
            super(new DeviceRegistry(), bus, SessionLogSink.NOOP);
        }

        @Override
        public void dispatch(TriggeredRule trigger, String caller) {
            triggered.add(trigger);
        }

        @Override
        public void eStop(String reason, String caller) {
            eStopReasons.add(reason);
            eStopCallers.add(caller);
        }

        @Override
        public void reset(String caller) {
            resetCallers.add(caller);
        }
    }
}
