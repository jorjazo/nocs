package dev.nocs.safety;

import java.time.Instant;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicReference;

public final class SafetyState {

    private final Map<String, SensorReading> readings = new ConcurrentHashMap<>();
    private final Set<String> latchedRules = ConcurrentHashMap.newKeySet();
    private final AtomicReference<ActiveTarget> activeTarget = new AtomicReference<>();
    private final AtomicReference<Double> lastAltitudeDeg = new AtomicReference<>();

    public void recordReading(SensorReading reading) {
        readings.put(reading.sensor(), reading);
    }

    public Optional<SensorReading> lastReading(String sensor) {
        return Optional.ofNullable(readings.get(sensor));
    }

    public Optional<Instant> lastSeen(String sensor) {
        return lastReading(sensor).map(SensorReading::ts);
    }

    public Map<String, SensorReading> readings() {
        return Map.copyOf(readings);
    }

    public void setActiveTarget(ActiveTarget t) {
        activeTarget.set(t);
        if (t == null) {
            lastAltitudeDeg.set(null);
        }
    }

    public Optional<ActiveTarget> activeTarget() {
        return Optional.ofNullable(activeTarget.get());
    }

    public void setLastAltitudeDeg(Double altDeg) {
        lastAltitudeDeg.set(altDeg);
    }

    public Optional<Double> lastAltitudeDeg() {
        return Optional.ofNullable(lastAltitudeDeg.get());
    }

    public boolean isLatched(String ruleName) {
        return latchedRules.contains(ruleName);
    }

    public void latch(String ruleName) {
        latchedRules.add(ruleName);
    }

    public void unlatch(String ruleName) {
        latchedRules.remove(ruleName);
    }

    public void unlatchAll() {
        latchedRules.clear();
    }

    public Set<String> latchedRules() {
        return Set.copyOf(latchedRules);
    }
}
