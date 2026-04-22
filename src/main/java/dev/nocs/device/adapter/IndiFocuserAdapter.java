package dev.nocs.device.adapter;

import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceKind;
import dev.nocs.device.DeviceStateChanged;
import dev.nocs.device.Focuser;
import dev.nocs.device.FocuserState;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.indi.IndiClient;
import dev.nocs.indi.IndiProperty;
import java.io.IOException;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

public class IndiFocuserAdapter implements Focuser {

    private final String indiName;
    private final DeviceId id;
    private final IndiClient client;
    private final EventBus bus;
    private final AtomicReference<FocuserState> state = new AtomicReference<>(FocuserState.DISCONNECTED);
    private final AtomicInteger position = new AtomicInteger();

    public IndiFocuserAdapter(String indiName, DeviceId id, IndiClient client, EventBus bus) {
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
        return DeviceKind.FOCUSER;
    }

    @Override
    public boolean isConnected() {
        return state.get() != FocuserState.DISCONNECTED;
    }

    @Override
    public FocuserState state() {
        return state.get();
    }

    @Override
    public int currentPosition() {
        return position.get();
    }

    @Override
    public void connect() {
        try {
            client.setSwitch(indiName, "CONNECTION", Map.of("CONNECT", true, "DISCONNECT", false));
        } catch (IOException e) {
            throw new RuntimeException("focuser connect failed", e);
        }
    }

    @Override
    public void disconnect() {
        try {
            client.setSwitch(indiName, "CONNECTION", Map.of("CONNECT", false, "DISCONNECT", true));
        } catch (IOException e) {
            throw new RuntimeException("focuser disconnect failed", e);
        }
    }

    @Override
    public void moveAbsolute(int pos) {
        try {
            client.setNumber(indiName, "ABS_FOCUS_POSITION", Map.of("FOCUS_ABSOLUTE_POSITION", (double) pos));
        } catch (IOException e) {
            throw new RuntimeException("moveAbsolute failed", e);
        }
    }

    @Override
    public void moveRelative(int delta) {
        moveAbsolute(position.get() + delta);
    }

    @Override
    public void abort() {
        try {
            client.setSwitch(indiName, "FOCUS_ABORT_MOTION", Map.of("ABORT", true));
        } catch (IOException e) {
            throw new RuntimeException("focuser abort failed", e);
        }
    }

    public void onProperty(IndiProperty p) {
        if (!p.device().equals(indiName)) {
            return;
        }
        FocuserState next = state.get();
        if (p instanceof IndiProperty.SwitchVector sw && sw.name().equals("CONNECTION")) {
            boolean connected = Boolean.TRUE.equals(sw.elements().get("CONNECT"));
            next = connected
                    ? (next == FocuserState.DISCONNECTED ? FocuserState.IDLE : next)
                    : FocuserState.DISCONNECTED;
        } else if (p instanceof IndiProperty.NumberVector n && n.name().equals("ABS_FOCUS_POSITION")) {
            Double v = n.elements().get("FOCUS_ABSOLUTE_POSITION");
            if (v != null) {
                position.set((int) Math.round(v));
            }
            next = switch (n.state()) {
                case BUSY -> FocuserState.MOVING;
                case OK, IDLE -> FocuserState.IDLE;
                case ALERT -> FocuserState.ERROR;
            };
        }
        transition(next);
    }

    private void transition(FocuserState next) {
        FocuserState prev = state.getAndSet(next);
        if (prev == next) {
            return;
        }
        DeviceStateChanged payload = new DeviceStateChanged(id, DeviceKind.FOCUSER, prev.name(), next.name());
        bus.publish(Event.of(Topic.FOCUSER, "state_changed", payload.toPayload()));
    }
}
