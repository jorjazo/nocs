package dev.nocs.device.adapter;

import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceKind;
import dev.nocs.device.DeviceStateChanged;
import dev.nocs.device.Mount;
import dev.nocs.device.MountState;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.indi.IndiClient;
import dev.nocs.indi.IndiProperty;
import java.io.IOException;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

public class IndiMountAdapter implements Mount {

    private final String indiName;
    private final DeviceId id;
    private final IndiClient client;
    private final EventBus bus;
    private final AtomicReference<MountState> state = new AtomicReference<>(MountState.DISCONNECTED);

    public IndiMountAdapter(String indiName, DeviceId id, IndiClient client, EventBus bus) {
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
        return DeviceKind.MOUNT;
    }

    @Override
    public boolean isConnected() {
        return state.get() != MountState.DISCONNECTED;
    }

    @Override
    public MountState state() {
        return state.get();
    }

    @Override
    public void connect() {
        try {
            client.setSwitch(indiName, "CONNECTION", Map.of("CONNECT", true, "DISCONNECT", false));
        } catch (IOException e) {
            throw new RuntimeException("mount connect failed", e);
        }
    }

    @Override
    public void disconnect() {
        try {
            client.setSwitch(indiName, "CONNECTION", Map.of("CONNECT", false, "DISCONNECT", true));
        } catch (IOException e) {
            throw new RuntimeException("mount disconnect failed", e);
        }
    }

    @Override
    public void slew(double raHours, double decDegrees) {
        try {
            client.setSwitch(indiName, "ON_COORD_SET", Map.of("SLEW", true, "TRACK", false, "SYNC", false));
            client.setNumber(indiName, "EQUATORIAL_EOD_COORD", Map.of("RA", raHours, "DEC", decDegrees));
        } catch (IOException e) {
            throw new RuntimeException("slew failed", e);
        }
    }

    @Override
    public void syncTo(double raHours, double decDegrees) {
        try {
            client.setSwitch(indiName, "ON_COORD_SET", Map.of("SLEW", false, "TRACK", false, "SYNC", true));
            client.setNumber(indiName, "EQUATORIAL_EOD_COORD", Map.of("RA", raHours, "DEC", decDegrees));
        } catch (IOException e) {
            throw new RuntimeException("sync failed", e);
        }
    }

    @Override
    public void park() {
        try {
            client.setSwitch(indiName, "TELESCOPE_PARK", Map.of("PARK", true, "UNPARK", false));
        } catch (IOException e) {
            throw new RuntimeException("park failed", e);
        }
    }

    @Override
    public void unpark() {
        try {
            client.setSwitch(indiName, "TELESCOPE_PARK", Map.of("PARK", false, "UNPARK", true));
        } catch (IOException e) {
            throw new RuntimeException("unpark failed", e);
        }
    }

    @Override
    public void abort() {
        try {
            client.setSwitch(indiName, "TELESCOPE_ABORT_MOTION", Map.of("ABORT", true));
        } catch (IOException e) {
            throw new RuntimeException("abort failed", e);
        }
    }

    public void onProperty(IndiProperty p) {
        if (!p.device().equals(indiName)) {
            return;
        }
        MountState next = state.get();
        if (p instanceof IndiProperty.SwitchVector sw) {
            if (sw.name().equals("CONNECTION")) {
                boolean connected = Boolean.TRUE.equals(sw.elements().get("CONNECT"));
                next = connected
                        ? (next == MountState.DISCONNECTED ? MountState.IDLE : next)
                        : MountState.DISCONNECTED;
            } else if (sw.name().equals("TELESCOPE_PARK")) {
                if (Boolean.TRUE.equals(sw.elements().get("PARK"))) {
                    next = MountState.PARKED;
                } else if (Boolean.TRUE.equals(sw.elements().get("UNPARK"))) {
                    next = MountState.IDLE;
                }
            }
        } else if (p instanceof IndiProperty.NumberVector n && n.name().equals("EQUATORIAL_EOD_COORD")) {
            next = switch (n.state()) {
                case BUSY -> MountState.SLEWING;
                case OK -> MountState.TRACKING;
                case ALERT -> MountState.ERROR;
                case IDLE -> (state.get() == MountState.SLEWING ? MountState.TRACKING : state.get());
            };
        }
        transition(next);
    }

    private void transition(MountState next) {
        MountState prev = state.getAndSet(next);
        if (prev == next) {
            return;
        }
        DeviceStateChanged payload = new DeviceStateChanged(id, DeviceKind.MOUNT, prev.name(), next.name());
        bus.publish(Event.of(Topic.MOUNT, "state_changed", payload.toPayload()));
    }
}
