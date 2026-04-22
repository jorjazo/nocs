package dev.nocs.device.adapter;

import dev.nocs.device.DeviceId;
import dev.nocs.device.FilterWheelState;
import dev.nocs.events.EventBus;
import dev.nocs.indi.IndiClient;
import dev.nocs.indi.IndiProperty;
import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

class IndiFilterWheelAdapterTest {

    private final IndiClient client = mock(IndiClient.class);
    private final EventBus bus = new EventBus();

    private IndiFilterWheelAdapter wheel() {
        return new IndiFilterWheelAdapter("Filter Simulator", new DeviceId("filter-simulator"), client, bus);
    }

    @Test
    void selectSlotIssuesNumber() throws Exception {
        IndiFilterWheelAdapter w = wheel();
        w.selectSlot(3);
        verify(client).setNumber(
                eq("Filter Simulator"), eq("FILTER_SLOT"), eq(Map.of("FILTER_SLOT_VALUE", 3.0)));
    }

    @Test
    void movesAndSettles() {
        IndiFilterWheelAdapter w = wheel();
        w.onProperty(connection(true));
        assertThat(w.state()).isEqualTo(FilterWheelState.IDLE);

        w.onProperty(slotVector(IndiProperty.State.BUSY, 2));
        assertThat(w.state()).isEqualTo(FilterWheelState.MOVING);

        w.onProperty(slotVector(IndiProperty.State.OK, 2));
        assertThat(w.state()).isEqualTo(FilterWheelState.IDLE);
        assertThat(w.currentSlot()).isEqualTo(2);
    }

    private IndiProperty connection(boolean connected) {
        return new IndiProperty.SwitchVector(
                "Filter Simulator",
                "CONNECTION",
                IndiProperty.State.OK,
                Instant.now(),
                IndiProperty.SwitchRule.ONE_OF_MANY,
                Map.of("CONNECT", connected, "DISCONNECT", !connected));
    }

    private IndiProperty slotVector(IndiProperty.State state, int value) {
        return new IndiProperty.NumberVector(
                "Filter Simulator",
                "FILTER_SLOT",
                state,
                Instant.now(),
                Map.of("FILTER_SLOT_VALUE", (double) value));
    }
}
