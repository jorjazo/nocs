package dev.nocs.image;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class CaptureContextTest {

    @Test
    void defaultsAreSensible() {
        CaptureContext ctx = CaptureContext.defaults(120.0);
        assertThat(ctx.filter()).isEqualTo("UNK");
        assertThat(ctx.target()).isEqualTo("untargeted");
        assertThat(ctx.step()).isEmpty();
        assertThat(ctx.seq()).isZero();
        assertThat(ctx.exposureSec()).isEqualTo(120.0);
    }

    @Test
    void blanksAreCoercedToDefaults() {
        CaptureContext ctx = new CaptureContext("  ", "", 60.0, null, 0);
        assertThat(ctx.filter()).isEqualTo("UNK");
        assertThat(ctx.target()).isEqualTo("untargeted");
        assertThat(ctx.step()).isEmpty();
    }

    @Test
    void rejectsNegativeExposure() {
        assertThat(org.junit.jupiter.api.Assertions.assertThrows(
                        IllegalArgumentException.class,
                        () -> new CaptureContext("L", "m31", -1.0, "L_120s", 1))
                .getMessage())
                .contains("exposureSec");
    }
}
