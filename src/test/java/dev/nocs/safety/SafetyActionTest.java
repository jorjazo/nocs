package dev.nocs.safety;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class SafetyActionTest {

    @Test
    void wireMatchesYamlVocabulary() {
        assertThat(SafetyAction.PAUSE_SEQUENCE.wire()).isEqualTo("pause_sequence");
        assertThat(SafetyAction.ABORT_AND_PARK.wire()).isEqualTo("abort_and_park");
        assertThat(SafetyAction.E_STOP.wire()).isEqualTo("e_stop");
    }

    @Test
    void fromWireRoundTrips() {
        assertThat(SafetyAction.fromWire("pause_sequence")).isEqualTo(SafetyAction.PAUSE_SEQUENCE);
        assertThat(SafetyAction.fromWire("abort_and_park")).isEqualTo(SafetyAction.ABORT_AND_PARK);
        assertThat(SafetyAction.fromWire("e_stop")).isEqualTo(SafetyAction.E_STOP);
    }

    @Test
    void fromWireRejectsUnknown() {
        assertThatThrownBy(() -> SafetyAction.fromWire("nuke_everything"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("nuke_everything");
    }
}
