package dev.nocs.device.adapter;

import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceKind;
import dev.nocs.device.DeviceStateChanged;
import dev.nocs.device.FilterWheel;
import dev.nocs.device.FilterWheelState;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.indi.IndiClient;
import dev.nocs.indi.IndiProperty;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

public class IndiFilterWheelAdapter implements FilterWheel {

    private final String indiName;
    private final DeviceId id;
    private final IndiClient client;
    private final EventBus bus;
    private final AtomicReference<FilterWheelState> state = new AtomicReference<>(FilterWheelState.DISCONNECTED);
    private final AtomicInteger slot = new AtomicInteger();
    private volatile List<String> names = List.of();

    public IndiFilterWheelAdapter(String indiName, DeviceId id, IndiClient client, EventBus bus) {
        this.indiName = indiName;
        this.id = id;
        this.client = client;
        this.bus = bus;
    }

    @Override
    public DeviceId id() {
        return id;
    }

    @Override
    public String indiName() {
        return indiName;
    }

    @Override
    public DeviceKind kind() {
        return DeviceKind.FILTERWHEEL;
    }

    @Override
    public boolean isConnected() {
        return state.get() != FilterWheelState.DISCONNECTED;
    }

    @Override
    public FilterWheelState state() {
        return state.get();
    }

    @Override
    public List<String> slotNames() {
        return names;
    }

    @Override
    public int currentSlot() {
        return slot.get();
    }

    @Override
    public void connect() {
        try {
            client.setSwitch(indiName, "CONNECTION", Map.of("CONNECT", true, "DISCONNECT", false));
        } catch (IOException e) {
            throw new RuntimeException("filterwheel connect failed", e);
        }
    }

    @Override
    public void disconnect() {
        try {
            client.setSwitch(indiName, "CONNECTION", Map.of("CONNECT", false, "DISCONNECT", true));
        } catch (IOException e) {
            throw new RuntimeException("filterwheel disconnect failed", e);
        }
    }

    @Override
    public void selectSlot(int slotNumber) {
        try {
            client.setNumber(indiName, "FILTER_SLOT", Map.of("FILTER_SLOT_VALUE", (double) slotNumber));
        } catch (IOException e) {
            throw new RuntimeException("selectSlot failed", e);
        }
    }

    public void onProperty(IndiProperty p) {
        if (!p.device().equals(indiName)) {
            return;
        }
        FilterWheelState next = state.get();
        if (p instanceof IndiProperty.SwitchVector sw && sw.name().equals("CONNECTION")) {
            boolean connected = Boolean.TRUE.equals(sw.elements().get("CONNECT"));
            next = connected
                    ? (next == FilterWheelState.DISCONNECTED ? FilterWheelState.IDLE : next)
                    : FilterWheelState.DISCONNECTED;
        } else if (p instanceof IndiProperty.NumberVector n && n.name().equals("FILTER_SLOT")) {
            Double v = n.elements().get("FILTER_SLOT_VALUE");
            if (v != null) {
                slot.set((int) Math.round(v));
            }
            next = switch (n.state()) {
                case BUSY -> FilterWheelState.MOVING;
                case OK, IDLE -> FilterWheelState.IDLE;
                case ALERT -> FilterWheelState.ERROR;
            };
        } else if (p instanceof IndiProperty.TextVector t && t.name().equals("FILTER_NAME")) {
            List<String> newNames = new ArrayList<>(t.elements().values());
            names = List.copyOf(newNames);
        }
        transition(next);
    }

    private void transition(FilterWheelState next) {
        FilterWheelState prev = state.getAndSet(next);
        if (prev == next) {
            return;
        }
        DeviceStateChanged payload = new DeviceStateChanged(id, DeviceKind.FILTERWHEEL, prev.name(), next.name());
        bus.publish(Event.of(Topic.FILTERWHEEL, "state_changed", payload.toPayload()));
    }
}
