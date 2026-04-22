package dev.nocs.target;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class TargetIdTest {

    @Test
    void parsesValidId() {
        TargetId.Parsed p = TargetId.parse("messier:M31");
        assertThat(p.catalog()).isEqualTo("messier");
        assertThat(p.designator()).isEqualTo("M31");
    }

    @Test
    void roundTripsCaseOfDesignator() {
        TargetId.Parsed p = TargetId.parse("ic:IC5146");
        assertThat(p.format()).isEqualTo("ic:IC5146");
    }

    @Test
    void rejectsEmpty() {
        assertThatThrownBy(() -> TargetId.parse("")).isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void rejectsMissingColon() {
        assertThatThrownBy(() -> TargetId.parse("M31")).isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void lowercasesCatalogPrefix() {
        TargetId.Parsed p = TargetId.parse("Messier:M31");
        assertThat(p.catalog()).isEqualTo("messier");
    }

    @Test
    void customIdAcceptsNumeric() {
        TargetId.Parsed p = TargetId.parse("custom:42");
        assertThat(p.catalog()).isEqualTo("custom");
        assertThat(p.designator()).isEqualTo("42");
    }
}
