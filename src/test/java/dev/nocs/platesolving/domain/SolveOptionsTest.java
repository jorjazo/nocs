package dev.nocs.platesolving.domain;

import dev.nocs.platesolving.SolveOptions;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SolveOptionsTest {

    @Test
    void defaultsAreEmpty() {
        SolveOptions opts = SolveOptions.defaults();
        assertThat(opts.raHintDeg()).isNull();
        assertThat(opts.decHintDeg()).isNull();
        assertThat(opts.radiusDeg()).isNull();
        assertThat(opts.pixelScaleArcsecPerPxHint()).isNull();
        assertThat(opts.timeoutSec()).isNull();
    }

    @Test
    void withTimeoutOverridesOnlyTimeout() {
        SolveOptions opts = SolveOptions.defaults().withTimeout(45.0);
        assertThat(opts.timeoutSec()).isEqualTo(45.0);
        assertThat(opts.raHintDeg()).isNull();
    }

    @Test
    void rejectsNegativeRadius() {
        org.junit.jupiter.api.Assertions.assertThrows(
                IllegalArgumentException.class,
                () -> new SolveOptions(0.0, 0.0, -1.0, null, null));
    }

    @Test
    void rejectsNegativeTimeout() {
        org.junit.jupiter.api.Assertions.assertThrows(
                IllegalArgumentException.class,
                () -> new SolveOptions(null, null, null, null, -3.0));
    }
}
