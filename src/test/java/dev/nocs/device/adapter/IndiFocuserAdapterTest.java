package dev.nocs.device.adapter;

import dev.nocs.device.DeviceId;
import dev.nocs.device.FocuserState;
import dev.nocs.events.EventBus;
import dev.nocs.indi.IndiClient;
import dev.nocs.indi.IndiProperty;
import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.reset;
import static org.mockito.Mockito.verify;

class IndiFocuserAdapterTest {

    private final IndiClient client = mock(IndiClient.class);
    private final EventBus bus = new EventBus();

    private IndiFocuserAdapter focuser() {
        return new IndiFocuserAdapter("Focuser Simulator", new DeviceId("focuser-simulator"), client, bus);
    }

    @Test
    void moveAbsoluteIssuesNumber() throws Exception {
        IndiFocuserAdapter f = focuser();
        f.moveAbsolute(12500);
        verify(client).setNumber(
                eq("Focuser Simulator"),
                eq("ABS_FOCUS_POSITION"),
                eq(Map.of("FOCUS_ABSOLUTE_POSITION", 12500.0)));
    }

    @Test
    void moveRelativeComputesAbsoluteFromCurrent() throws Exception {
        IndiFocuserAdapter f = focuser();
        f.onProperty(absPos(IndiProperty.State.OK, 10000));
        reset(client);

        f.moveRelative(-200);
        verify(client).setNumber(
                eq("Focuser Simulator"),
                eq("ABS_FOCUS_POSITION"),
                eq(Map.of("FOCUS_ABSOLUTE_POSITION", 9800.0)));
    }

    @Test
    void stateFollowsAbsPosition() {
        IndiFocuserAdapter f = focuser();
        f.onProperty(connection(true));
        assertThat(f.state()).isEqualTo(FocuserState.IDLE);

        f.onProperty(absPos(IndiProperty.State.BUSY, 11000));
        assertThat(f.state()).isEqualTo(FocuserState.MOVING);

        f.onProperty(absPos(IndiProperty.State.OK, 11000));
        assertThat(f.state()).isEqualTo(FocuserState.IDLE);
        assertThat(f.currentPosition()).isEqualTo(11000);
    }

    private IndiProperty connection(boolean connected) {
        return new IndiProperty.SwitchVector(
                "Focuser Simulator",
                "CONNECTION",
                IndiProperty.State.OK,
                Instant.now(),
                IndiProperty.SwitchRule.ONE_OF_MANY,
                Map.of("CONNECT", connected, "DISCONNECT", !connected));
    }

    private IndiProperty absPos(IndiProperty.State state, int pos) {
        return new IndiProperty.NumberVector(
                "Focuser Simulator",
                "ABS_FOCUS_POSITION",
                state,
                Instant.now(),
                Map.of("FOCUS_ABSOLUTE_POSITION", (double) pos));
    }
}
