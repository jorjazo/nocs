package dev.nocs.safety;

import dev.nocs.device.Camera;
import dev.nocs.device.Device;
import dev.nocs.device.DeviceKind;
import dev.nocs.device.DeviceRegistry;
import dev.nocs.device.Mount;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import java.util.LinkedHashMap;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class SafetyActionDispatcher {

    private static final Logger log = LoggerFactory.getLogger(SafetyActionDispatcher.class);

    private final DeviceRegistry registry;
    private final EventBus bus;
    private final SessionLogSink sessionLog;

    public SafetyActionDispatcher(DeviceRegistry registry, EventBus bus, SessionLogSink sessionLog) {
        this.registry = registry;
        this.bus = bus;
        this.sessionLog = sessionLog == null ? SessionLogSink.NOOP : sessionLog;
    }

    public void dispatch(TriggeredRule trigger, String caller) {
        SafetyRule rule = trigger.rule();
        Map<String, Object> ruleEvent = new LinkedHashMap<>();
        ruleEvent.put("rule", rule.name());
        ruleEvent.put("action", rule.action().wire());
        ruleEvent.put("caller", caller);
        bus.publish(Event.of(Topic.SAFETY, "rule_triggered", ruleEvent));
        sessionLog.log(Topic.SAFETY.wire(), "rule_triggered", ruleEvent);

        switch (rule.action()) {
            case PAUSE_SEQUENCE -> publishSequence("pause_requested", "rule:" + rule.name(), caller);
            case ABORT_AND_PARK -> {
                publishSequence("abort_requested", "rule:" + rule.name(), caller);
                forEachMount(this::safePark);
            }
            case E_STOP -> eStop("rule:" + rule.name(), caller);
        }
    }

    public void eStop(String reason, String caller) {
        Map<String, Object> payload =
                Map.of("reason", reason == null ? "manual" : reason, "caller", caller == null ? "unknown" : caller);

        forEachCamera(this::safeAbortExposure);
        forEachCamera(Device::emergencyStop);
        forEachMount(this::safePark);
        forEachMount(Device::emergencyStop);

        publishSequence("abort_requested", reason == null ? "e_stop" : reason, caller);
        bus.publish(Event.of(Topic.SAFETY, "e_stopped", payload));
        sessionLog.log(Topic.SAFETY.wire(), "e_stop", payload);
    }

    public void reset(String caller) {
        for (Device d : registry.all()) {
            try {
                d.resetEStop();
            } catch (RuntimeException e) {
                log.warn("device {} resetEStop failed: {}", d.id().value(), e.getMessage());
            }
        }
        Map<String, Object> payload = Map.of("caller", caller == null ? "unknown" : caller);
        bus.publish(Event.of(Topic.SAFETY, "reset", payload));
        sessionLog.log(Topic.SAFETY.wire(), "reset", payload);
    }

    private void publishSequence(String type, String reason, String caller) {
        Map<String, Object> payload =
                Map.of("reason", reason == null ? "" : reason, "caller", caller == null ? "unknown" : caller);
        bus.publish(Event.of(Topic.SEQUENCE, type, payload));
    }

    private void forEachMount(java.util.function.Consumer<Mount> fn) {
        for (Device d : registry.all()) {
            if (d.kind() == DeviceKind.MOUNT && d.isConnected() && d instanceof Mount m) {
                fn.accept(m);
            }
        }
    }

    private void forEachCamera(java.util.function.Consumer<Camera> fn) {
        for (Device d : registry.all()) {
            if (d.kind() == DeviceKind.CAMERA && d.isConnected() && d instanceof Camera c) {
                fn.accept(c);
            }
        }
    }

    private void safePark(Mount m) {
        try {
            m.park();
        } catch (RuntimeException e) {
            log.warn("mount {} park failed: {}", m.id().value(), e.getMessage());
        }
    }

    private void safeAbortExposure(Camera c) {
        try {
            c.abortExposure();
        } catch (RuntimeException e) {
            log.warn("camera {} abort failed: {}", c.id().value(), e.getMessage());
        }
    }
}
