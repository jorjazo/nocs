package dev.nocs.device;

import dev.nocs.device.adapter.IndiCameraAdapter;
import dev.nocs.device.adapter.IndiDeviceFactory;
import dev.nocs.device.adapter.IndiFilterWheelAdapter;
import dev.nocs.device.adapter.IndiFocuserAdapter;
import dev.nocs.device.adapter.IndiMountAdapter;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.indi.IndiClient;
import dev.nocs.indi.IndiProperty;
import dev.nocs.indi.PropertyUpdate;
import jakarta.annotation.PreDestroy;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.concurrent.ConcurrentHashMap;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import reactor.core.Disposable;

public class DeviceService {

    private static final Logger log = LoggerFactory.getLogger(DeviceService.class);

    private final IndiClient client;
    private final EventBus bus;
    private final CameraImageSink sink;
    private final DeviceRegistry registry = new DeviceRegistry();
    private final Map<String, DeviceId> deviceIdsByIndiName = new ConcurrentHashMap<>();
    private final Disposable subscription;

    public DeviceService(IndiClient client, EventBus bus, CameraImageSink sink) {
        this.client = client;
        this.bus = bus;
        this.sink = sink;
        this.subscription = client.updates().subscribe(this::onUpdate, e -> log.warn("INDI updates error", e));
        client.onBlob(
                (deviceName, propertyName, format, bytes) -> onBlob(deviceName, format, bytes));
    }

    private void onBlob(String deviceName, String format, byte[] bytes) {
        DeviceId id = deviceIdsByIndiName.get(deviceName);
        if (id == null) {
            sink.accept(DeviceId.slug(deviceName), bytes, format);
            return;
        }
        registry.find(id)
                .ifPresentOrElse(
                        d -> {
                            if (d instanceof IndiCameraAdapter cam) {
                                cam.onBlob(bytes, format);
                            } else {
                                sink.accept(id, bytes, format);
                            }
                        },
                        () -> sink.accept(DeviceId.slug(deviceName), bytes, format));
    }

    public DeviceRegistry registry() {
        return registry;
    }

    public java.util.Collection<Device> list() {
        return registry.all();
    }

    public void connect(DeviceId id) {
        device(id).connect();
    }

    public void disconnect(DeviceId id) {
        device(id).disconnect();
    }

    private Device device(DeviceId id) {
        return registry.find(id).orElseThrow(() -> new NoSuchElementException("unknown device: " + id.value()));
    }

    private void onUpdate(PropertyUpdate update) {
        IndiProperty p = update.property();
        String indiDevice = p.device();
        if (registry.find(DeviceId.slug(indiDevice)).isEmpty()) {
            Device d = IndiDeviceFactory.create(indiDevice, client.properties(indiDevice), client, bus, sink);
            if (d == null) {
                return;
            }
            registry.add(d);
            deviceIdsByIndiName.put(indiDevice, d.id());
            bus.publish(Event.of(
                    Topic.DEVICE_CONNECTION,
                    "discovered",
                    Map.of(
                            "id",
                            d.id().value(),
                            "indiName",
                            indiDevice,
                            "kind",
                            d.kind().name().toLowerCase())));
            for (IndiProperty prop : client.properties(indiDevice)) {
                dispatchProperty(d, prop);
            }
            return;
        }
        DeviceId id = deviceIdsByIndiName.getOrDefault(indiDevice, DeviceId.slug(indiDevice));
        registry.find(id).ifPresent(d -> dispatchProperty(d, p));
    }

    private void dispatchProperty(Device d, IndiProperty p) {
        if (d instanceof IndiMountAdapter a) {
            a.onProperty(p);
        } else if (d instanceof IndiCameraAdapter c) {
            c.onProperty(p);
        } else if (d instanceof IndiFilterWheelAdapter w) {
            w.onProperty(p);
        } else if (d instanceof IndiFocuserAdapter f) {
            f.onProperty(p);
        }
    }

    @PreDestroy
    public void shutdown() {
        try {
            subscription.dispose();
        } catch (Exception ignored) {
        }
    }
}
