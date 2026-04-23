package dev.nocs.safety;

import dev.nocs.astronomy.Horizontal;
import dev.nocs.astronomy.Precession;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.observatory.ObservatoryService;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.EnumSet;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import reactor.core.Disposable;

public class SafetyService {

    private static final Logger log = LoggerFactory.getLogger(SafetyService.class);

    private final EventBus bus;
    private final SafetyActionDispatcher dispatcher;
    private final SafetyRuleEngine engine;
    private final SafetyState state;
    private final SafetyRuleParser parser;
    private final ObservatoryService observatoryService;
    private final Path rulesPath;
    private final long altitudeIntervalMs;
    private final long sensorOfflineDefaultSeconds;

    private final AtomicReference<List<SafetyRule>> rules = new AtomicReference<>(List.of());
    private final java.util.concurrent.ScheduledExecutorService scheduler =
            java.util.concurrent.Executors.newSingleThreadScheduledExecutor(r -> {
                Thread t = new Thread(r, "safety-altitude-eval");
                t.setDaemon(true);
                return t;
            });
    private Disposable subscription;

    public SafetyService(
            EventBus bus,
            SafetyActionDispatcher dispatcher,
            SafetyRuleEngine engine,
            SafetyState state,
            SafetyRuleParser parser,
            ObservatoryService observatoryService,
            Path rulesPath,
            long altitudeIntervalMs,
            long sensorOfflineDefaultSeconds) {
        this.bus = bus;
        this.dispatcher = dispatcher;
        this.engine = engine;
        this.state = state;
        this.parser = parser;
        this.observatoryService = observatoryService;
        this.rulesPath = rulesPath;
        this.altitudeIntervalMs = altitudeIntervalMs;
        this.sensorOfflineDefaultSeconds = sensorOfflineDefaultSeconds;
    }

    @PostConstruct
    public void start() {
        subscription = bus
                .subscribe(EnumSet.of(Topic.SENSOR, Topic.SEQUENCE))
                .subscribe(this::onBusEvent, e -> log.warn("safety bus subscription error", e));
        scheduler.scheduleAtFixedRate(
                this::evaluateAltitudeNow, altitudeIntervalMs, altitudeIntervalMs, java.util.concurrent.TimeUnit.MILLISECONDS);
        try {
            reload();
        } catch (RuntimeException e) {
            log.warn("safety rules failed to load on startup: {}", e.getMessage());
        }
    }

    @PreDestroy
    public void stop() {
        if (subscription != null) {
            subscription.dispose();
        }
        scheduler.shutdownNow();
    }

    public synchronized void reload() {
        if (rulesPath == null || !Files.exists(rulesPath)) {
            rules.set(List.of());
            log.info("safety rules path missing or empty; rule engine inactive ({})", rulesPath);
            return;
        }
        try {
            List<SafetyRule> parsed = parser.parse(Files.newInputStream(rulesPath));
            rules.set(parsed);
            log.info("safety rules loaded: {} rules from {}", parsed.size(), rulesPath);
        } catch (IOException e) {
            throw new IllegalStateException("could not read " + rulesPath, e);
        }
    }

    public List<SafetyRule> rules() {
        return rules.get();
    }

    public SafetyState stateSnapshot() {
        return state;
    }

    /**
     * Ingests a reading from the REST API. Does not re-publish to the event bus, so subscribers are not
     * notified twice (this service also subscribes to {@link Topic#SENSOR} for external publishers).
     */
    public void postReading(SensorReading reading, String caller) {
        state.recordReading(reading);
        evaluate(caller == null ? "http" : caller);
    }

    public void setActiveTarget(ActiveTarget target, String caller) {
        state.setActiveTarget(target);
        evaluateAltitudeNow();
        if (target != null) {
            bus.publish(
                    Event.of(Topic.SEQUENCE, "target_active", Map.of("target_id", target.targetId(), "ra_j2000_deg", target.raJ2000Deg(), "dec_j2000_deg", target.decJ2000Deg(), "caller", caller == null ? "unknown" : caller)));
        }
    }

    public void eStop(String reason, String caller) {
        dispatcher.eStop(reason, caller);
    }

    public void reset(String caller) {
        state.unlatchAll();
        dispatcher.reset(caller);
    }

    public void evaluateAltitudeNow() {
        var at = state.activeTarget();
        if (at.isEmpty()) {
            state.setLastAltitudeDeg(null);
            return;
        }
        var loc = observatoryService.activeLocation();
        if (loc.isEmpty()) {
            state.setLastAltitudeDeg(null);
            return;
        }
        Instant now = Instant.now();
        double[] jnow = Precession.precessFromJ2000(at.get().raJ2000Deg(), at.get().decJ2000Deg(), now);
        double[] altaz = Horizontal.equatorialToHorizontal(jnow[0], jnow[1], loc.get(), now, true);
        state.setLastAltitudeDeg(altaz[0]);
        evaluate("scheduler");
    }

    private void evaluate(String caller) {
        List<SafetyRule> snapshot = rules.get();
        if (snapshot.isEmpty()) {
            return;
        }
        List<TriggeredRule> fired = engine.evaluate(state, snapshot);
        for (TriggeredRule t : fired) {
            dispatcher.dispatch(t, caller);
        }
    }

    private void onBusEvent(Event event) {
        if (event.topic() == Topic.SENSOR && "reading".equals(event.type())) {
            ingestSensorEvent(event);
        } else if (event.topic() == Topic.SEQUENCE && "target_active".equals(event.type())) {
            ingestActiveTargetEvent(event);
        }
    }

    @SuppressWarnings("unchecked")
    private void ingestSensorEvent(Event event) {
        Object sensor = event.payload().get("sensor");
        Object values = event.payload().get("values");
        Object caller = event.payload().get("caller");
        if (!(sensor instanceof String s) || !(values instanceof Map<?, ?> v)) {
            return;
        }
        Instant ts = parseTs(event.payload().get("ts"));
        SensorReading r = new SensorReading(s, ts, (Map<String, Object>) v);
        state.recordReading(r);
        evaluate(caller == null ? "bus" : caller.toString());
    }

    private void ingestActiveTargetEvent(Event event) {
        Object idObj = event.payload().get("target_id");
        Object raObj = event.payload().get("ra_j2000_deg");
        Object decObj = event.payload().get("dec_j2000_deg");
        if (!(idObj instanceof String id) || !(raObj instanceof Number ra) || !(decObj instanceof Number dec)) {
            return;
        }
        state.setActiveTarget(new ActiveTarget(id, ra.doubleValue(), dec.doubleValue(), Instant.now()));
        evaluateAltitudeNow();
    }

    private Instant parseTs(Object raw) {
        if (raw instanceof String s) {
            try {
                return Instant.parse(s);
            } catch (Exception ignored) {
                // fall through
            }
        }
        return Instant.now();
    }

    public long sensorOfflineDefaultSeconds() {
        return sensorOfflineDefaultSeconds;
    }
}
