package dev.nocs.device.adapter;

import dev.nocs.device.Camera;
import dev.nocs.device.CameraImageSink;
import dev.nocs.device.CameraState;
import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceKind;
import dev.nocs.device.DeviceStateChanged;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.indi.IndiClient;
import dev.nocs.indi.IndiProperty;
import java.io.IOException;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

public class IndiCameraAdapter implements Camera {

    private final String indiName;
    private final DeviceId id;
    private final IndiClient client;
    private final EventBus bus;
    private final CameraImageSink sink;
    private final AtomicReference<CameraState> state = new AtomicReference<>(CameraState.DISCONNECTED);
    private volatile Double lastTemp;

    public IndiCameraAdapter(String indiName, DeviceId id, IndiClient client, EventBus bus, CameraImageSink sink) {
        this.indiName = indiName;
        this.id = id;
        this.client = client;
        this.bus = bus;
        this.sink = sink;
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
        return DeviceKind.CAMERA;
    }

    @Override
    public boolean isConnected() {
        return state.get() != CameraState.DISCONNECTED;
    }

    @Override
    public CameraState state() {
        return state.get();
    }

    @Override
    public Double currentTemperatureCelsius() {
        return lastTemp;
    }

    @Override
    public void connect() {
        try {
            client.setSwitch(indiName, "CONNECTION", Map.of("CONNECT", true, "DISCONNECT", false));
            client.setSwitch(
                    indiName,
                    "UPLOAD_MODE",
                    Map.of("UPLOAD_CLIENT", true, "UPLOAD_LOCAL", false, "UPLOAD_BOTH", false));
            client.enableBlob(indiName, "Also");
        } catch (IOException e) {
            throw new RuntimeException("camera connect failed", e);
        }
    }

    @Override
    public void disconnect() {
        try {
            client.setSwitch(indiName, "CONNECTION", Map.of("CONNECT", false, "DISCONNECT", true));
        } catch (IOException e) {
            throw new RuntimeException("camera disconnect failed", e);
        }
    }

    @Override
    public void cool(double setpointCelsius) {
        try {
            client.setSwitch(indiName, "CCD_COOLER", Map.of("COOLER_ON", true, "COOLER_OFF", false));
            client.setNumber(indiName, "CCD_TEMPERATURE", Map.of("CCD_TEMPERATURE_VALUE", setpointCelsius));
        } catch (IOException e) {
            throw new RuntimeException("camera cool failed", e);
        }
    }

    @Override
    public void expose(double durationSeconds) {
        try {
            client.setNumber(indiName, "CCD_EXPOSURE", Map.of("CCD_EXPOSURE_VALUE", durationSeconds));
        } catch (IOException e) {
            throw new RuntimeException("expose failed", e);
        }
    }

    @Override
    public void abortExposure() {
        try {
            client.setSwitch(indiName, "CCD_ABORT_EXPOSURE", Map.of("ABORT", true));
        } catch (IOException e) {
            throw new RuntimeException("abort exposure failed", e);
        }
    }

    public void onProperty(IndiProperty p) {
        if (!p.device().equals(indiName)) {
            return;
        }
        CameraState next = state.get();
        if (p instanceof IndiProperty.SwitchVector sw && sw.name().equals("CONNECTION")) {
            boolean connected = Boolean.TRUE.equals(sw.elements().get("CONNECT"));
            next = connected
                    ? (next == CameraState.DISCONNECTED ? CameraState.IDLE : next)
                    : CameraState.DISCONNECTED;
        } else if (p instanceof IndiProperty.NumberVector n) {
            if (n.name().equals("CCD_EXPOSURE")) {
                if (n.state() == IndiProperty.State.BUSY) {
                    next = CameraState.EXPOSING;
                } else if (n.state() == IndiProperty.State.ALERT) {
                    next = CameraState.ERROR;
                }
            } else if (n.name().equals("CCD_TEMPERATURE")) {
                Double t = n.elements().get("CCD_TEMPERATURE_VALUE");
                if (t != null) {
                    lastTemp = t;
                }
                if (n.state() == IndiProperty.State.BUSY) {
                    next = CameraState.COOLING;
                } else if (n.state() == IndiProperty.State.OK && state.get() == CameraState.COOLING) {
                    next = CameraState.READY;
                }
            }
        }
        transition(next);
    }

    public void onBlob(byte[] bytes, String format) {
        CameraState prev = state.getAndSet(CameraState.DOWNLOADING);
        if (prev != CameraState.DOWNLOADING) {
            publishStateEvent(prev, CameraState.DOWNLOADING);
        }
        sink.accept(id, bytes, format == null ? ".fits" : format);
        transition(CameraState.IDLE);
    }

    private void transition(CameraState next) {
        CameraState prev = state.getAndSet(next);
        if (prev == next) {
            return;
        }
        publishStateEvent(prev, next);
    }

    private void publishStateEvent(CameraState prev, CameraState next) {
        DeviceStateChanged payload = new DeviceStateChanged(id, DeviceKind.CAMERA, prev.name(), next.name());
        bus.publish(Event.of(Topic.CAMERA, "state_changed", payload.toPayload()));
    }
}
