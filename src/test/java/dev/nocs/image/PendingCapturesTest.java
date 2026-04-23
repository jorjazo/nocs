package dev.nocs.image;

import dev.nocs.device.DeviceId;
import java.util.Optional;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class PendingCapturesTest {

    @Test
    void prepareThenConsumeYieldsContextOnce() {
        PendingCaptures pending = new PendingCaptures();
        DeviceId cam = new DeviceId("ccd-sim");
        CaptureContext ctx = new CaptureContext("L", "m31", 30.0, "L_30s", 0);

        pending.prepare(cam, ctx);

        Optional<CaptureContext> first = pending.consume(cam);
        Optional<CaptureContext> second = pending.consume(cam);

        assertThat(first).contains(ctx);
        assertThat(second).isEmpty();
    }

    @Test
    void prepareReplacesPreviousPending() {
        PendingCaptures pending = new PendingCaptures();
        DeviceId cam = new DeviceId("ccd-sim");
        pending.prepare(cam, new CaptureContext("L", "m31", 30.0, "", 0));
        pending.prepare(cam, new CaptureContext("R", "m42", 60.0, "", 0));

        assertThat(pending.consume(cam))
                .map(CaptureContext::filter)
                .contains("R");
    }
}
