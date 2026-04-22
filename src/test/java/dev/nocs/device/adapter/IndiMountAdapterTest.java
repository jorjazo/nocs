package dev.nocs.device.adapter;

import dev.nocs.device.DeviceId;
import dev.nocs.device.MountState;
import dev.nocs.events.EventBus;
import dev.nocs.indi.IndiClient;
import dev.nocs.indi.IndiProperty;
import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

class IndiMountAdapterTest {

    private final IndiClient client = mock(IndiClient.class);
    private final EventBus bus = new EventBus();

    private IndiMountAdapter mount() {
        return new IndiMountAdapter("Telescope Simulator", new DeviceId("telescope-simulator"), client, bus);
    }

    @Test
    void connectSetsConnectionSwitch() throws Exception {
        IndiMountAdapter m = mount();
        m.connect();

        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, Boolean>> captor = ArgumentCaptor.forClass(Map.class);
        verify(client).setSwitch(eq("Telescope Simulator"), eq("CONNECTION"), captor.capture());
        assertThat(captor.getValue()).containsEntry("CONNECT", true).containsEntry("DISCONNECT", false);
    }

    @Test
    void slewIssuesCoordSetThenCoords() throws Exception {
        IndiMountAdapter m = mount();
        m.slew(0.712, 41.269);

        verify(client).setSwitch(
                eq("Telescope Simulator"),
                eq("ON_COORD_SET"),
                eq(Map.of("SLEW", true, "TRACK", false, "SYNC", false)));
        verify(client).setNumber(
                eq("Telescope Simulator"),
                eq("EQUATORIAL_EOD_COORD"),
                eq(Map.of("RA", 0.712, "DEC", 41.269)));
    }

    @Test
    void syncIssuesSyncThenCoords() throws Exception {
        IndiMountAdapter m = mount();
        m.syncTo(1.0, 2.0);

        verify(client).setSwitch(
                eq("Telescope Simulator"),
                eq("ON_COORD_SET"),
                eq(Map.of("SLEW", false, "TRACK", false, "SYNC", true)));
        verify(client).setNumber(
                eq("Telescope Simulator"), eq("EQUATORIAL_EOD_COORD"), eq(Map.of("RA", 1.0, "DEC", 2.0)));
    }

    @Test
    void parkIssuesParkSwitch() throws Exception {
        IndiMountAdapter m = mount();
        m.park();

        verify(client).setSwitch(
                eq("Telescope Simulator"),
                eq("TELESCOPE_PARK"),
                eq(Map.of("PARK", true, "UNPARK", false)));
    }

    @Test
    void stateTransitionsFromPropertyUpdates() {
        IndiMountAdapter m = mount();
        assertThat(m.state()).isEqualTo(MountState.DISCONNECTED);

        m.onProperty(connection(true));
        assertThat(m.state()).isEqualTo(MountState.IDLE);

        m.onProperty(eqCoord(IndiProperty.State.BUSY));
        assertThat(m.state()).isEqualTo(MountState.SLEWING);

        m.onProperty(eqCoord(IndiProperty.State.OK));
        assertThat(m.state()).isEqualTo(MountState.TRACKING);

        m.onProperty(parkSwitch(true));
        assertThat(m.state()).isEqualTo(MountState.PARKED);
    }

    private IndiProperty connection(boolean connected) {
        return new IndiProperty.SwitchVector(
                "Telescope Simulator",
                "CONNECTION",
                IndiProperty.State.OK,
                Instant.now(),
                IndiProperty.SwitchRule.ONE_OF_MANY,
                Map.of("CONNECT", connected, "DISCONNECT", !connected));
    }

    private IndiProperty eqCoord(IndiProperty.State state) {
        return new IndiProperty.NumberVector(
                "Telescope Simulator",
                "EQUATORIAL_EOD_COORD",
                state,
                Instant.now(),
                Map.of("RA", 0.0, "DEC", 0.0));
    }

    private IndiProperty parkSwitch(boolean parked) {
        return new IndiProperty.SwitchVector(
                "Telescope Simulator",
                "TELESCOPE_PARK",
                IndiProperty.State.OK,
                Instant.now(),
                IndiProperty.SwitchRule.ONE_OF_MANY,
                Map.of("PARK", parked, "UNPARK", !parked));
    }
}
