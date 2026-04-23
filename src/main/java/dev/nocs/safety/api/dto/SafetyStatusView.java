package dev.nocs.safety.api.dto;

import java.util.List;

public record SafetyStatusView(List<RuleView> rules, List<String> latched, String activeTargetId) {}
