package dev.nocs.safety;

public record SafetyRule(String name, SafetyCondition condition, SafetyAction action) {

    public SafetyRule {
        if (name == null || name.isBlank()) {
            throw new IllegalArgumentException("rule name is required");
        }
        if (condition == null) {
            throw new IllegalArgumentException("rule condition is required");
        }
        if (action == null) {
            throw new IllegalArgumentException("rule action is required");
        }
    }
}
