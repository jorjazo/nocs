package dev.nocs.safety;

import java.io.InputStream;
import java.util.List;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class SafetyRuleParserTest {

    @Test
    void parsesAllFourConditions() throws Exception {
        List<SafetyRule> rules;
        try (InputStream in = openFixture("rules-valid.yaml")) {
            rules = new SafetyRuleParser().parse(in);
        }

        assertThat(rules).hasSize(4);

        SafetyRule humidity = rules.get(0);
        assertThat(humidity.name()).isEqualTo("humidity-high");
        assertThat(humidity.condition()).isEqualTo(new SafetyCondition.HumidityAbove(90));
        assertThat(humidity.action()).isEqualTo(SafetyAction.PAUSE_SEQUENCE);

        assertThat(rules.get(1).condition()).isEqualTo(new SafetyCondition.RainDetected());
        assertThat(rules.get(1).action()).isEqualTo(SafetyAction.E_STOP);

        assertThat(rules.get(2).condition()).isEqualTo(new SafetyCondition.AltitudeBelow(20));
        assertThat(rules.get(2).action()).isEqualTo(SafetyAction.ABORT_AND_PARK);

        assertThat(rules.get(3).condition()).isEqualTo(new SafetyCondition.SensorOffline("weather", 120));
    }

    @Test
    void rejectsUnknownAction() throws Exception {
        try (InputStream in = openFixture("rules-invalid.yaml")) {
            assertThatThrownBy(() -> new SafetyRuleParser().parse(in))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("nuke_everything");
        }
    }

    @Test
    void emptyFileYieldsEmptyList() throws Exception {
        List<SafetyRule> rules = new SafetyRuleParser().parseString("");
        assertThat(rules).isEmpty();
    }

    @Test
    void rulesKeyMustExistOrReturnEmpty() throws Exception {
        List<SafetyRule> rules = new SafetyRuleParser().parseString("# comment only\n");
        assertThat(rules).isEmpty();
    }

    @Test
    void rejectsRuleMissingCondition() {
        String yaml = "rules:\n  - name: x\n    then: e_stop\n";
        assertThatThrownBy(() -> new SafetyRuleParser().parseString(yaml))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("when");
    }

    @Test
    void rejectsRuleMissingAction() {
        String yaml = "rules:\n  - name: x\n    when: { rain_detected: true }\n";
        assertThatThrownBy(() -> new SafetyRuleParser().parseString(yaml))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("then");
    }

    private InputStream openFixture(String name) {
        InputStream in = getClass().getClassLoader().getResourceAsStream("safety/" + name);
        if (in == null) {
            throw new IllegalStateException("fixture not on classpath: safety/" + name);
        }
        return in;
    }
}
