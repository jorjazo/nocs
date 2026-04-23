package dev.nocs.safety;

public enum SafetyAction {
    PAUSE_SEQUENCE,
    ABORT_AND_PARK,
    E_STOP;

    public String wire() {
        return name().toLowerCase();
    }

    public static SafetyAction fromWire(String wire) {
        if (wire == null) {
            throw new IllegalArgumentException("safety action is required");
        }
        try {
            return SafetyAction.valueOf(wire.trim().toUpperCase());
        } catch (IllegalArgumentException e) {
            throw new IllegalArgumentException("unknown safety action: " + wire, e);
        }
    }
}
