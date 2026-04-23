package dev.nocs.platesolving;

public enum SolverKind {
    ASTAP, DISABLED;

    public String wire() {
        return name().toLowerCase();
    }

    public static SolverKind fromWire(String s) {
        if (s == null || s.isBlank()) {
            return ASTAP;
        }
        return SolverKind.valueOf(s.trim().toUpperCase());
    }
}
