package dev.nocs.device;

import java.util.Collection;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

public class DeviceRegistry {

    private final Map<DeviceId, Device> devices = new ConcurrentHashMap<>();

    public void add(Device d) {
        devices.put(d.id(), d);
    }

    public void remove(DeviceId id) {
        devices.remove(id);
    }

    public Optional<Device> find(DeviceId id) {
        return Optional.ofNullable(devices.get(id));
    }

    public Collection<Device> all() {
        return devices.values();
    }

    public Optional<Mount> mount(DeviceId id) {
        return find(id).filter(d -> d.kind() == DeviceKind.MOUNT).map(Mount.class::cast);
    }

    public Optional<Camera> camera(DeviceId id) {
        return find(id).filter(d -> d.kind() == DeviceKind.CAMERA).map(Camera.class::cast);
    }

    public Optional<FilterWheel> filterWheel(DeviceId id) {
        return find(id).filter(d -> d.kind() == DeviceKind.FILTERWHEEL).map(FilterWheel.class::cast);
    }

    public Optional<Focuser> focuser(DeviceId id) {
        return find(id).filter(d -> d.kind() == DeviceKind.FOCUSER).map(Focuser.class::cast);
    }
}
