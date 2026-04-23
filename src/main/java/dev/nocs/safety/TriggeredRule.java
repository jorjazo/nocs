package dev.nocs.safety;

import java.time.Instant;

public record TriggeredRule(SafetyRule rule, SafetyCondition resolvedCondition, Instant at) {

    public TriggeredRule {
        if (rule == null || resolvedCondition == null || at == null) {
            throw new IllegalArgumentException("rule/condition/at all required");
        }
    }
}
