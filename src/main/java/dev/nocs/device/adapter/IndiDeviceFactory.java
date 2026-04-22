package dev.nocs.device.adapter;

import dev.nocs.device.CameraImageSink;
import dev.nocs.device.Device;
import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceKind;
import dev.nocs.events.EventBus;
import dev.nocs.indi.IndiClient;
import dev.nocs.indi.IndiProperty;
import java.util.Collection;
import java.util.Set;
import java.util.stream.Collectors;

public final class IndiDeviceFactory {

    private static final Set<String> MOUNT_HINTS =
            Set.of("EQUATORIAL_EOD_COORD", "TELESCOPE_PARK", "TELESCOPE_ABORT_MOTION");
    private static final Set<String> CAMERA_HINTS = Set.of("CCD_EXPOSURE", "CCD_TEMPERATURE", "CCD1");
    private static final Set<String> FILTER_HINTS = Set.of("FILTER_SLOT");
    private static final Set<String> FOCUSER_HINTS = Set.of("ABS_FOCUS_POSITION", "REL_FOCUS_POSITION");

    private IndiDeviceFactory() {}

    /**
     * INDI simulator drivers often omit mount/camera/filter/focuser property vectors until the device is
     * connected — but {@code DRIVER_INFO} is always present. Prefer {@code DRIVER_EXEC} for kind detection.
     */
    private static DeviceKind classifyFromDriverInfo(Collection<IndiProperty> props) {
        for (IndiProperty p : props) {
            if (p instanceof IndiProperty.TextVector t && "DRIVER_INFO".equals(t.name())) {
                String exec = t.elements().get("DRIVER_EXEC");
                if (exec == null) {
                    continue;
                }
                String e = exec.toLowerCase();
                if (e.contains("telescope")) {
                    return DeviceKind.MOUNT;
                }
                if (e.contains("ccd")) {
                    return DeviceKind.CAMERA;
                }
                if (e.contains("focus")) {
                    return DeviceKind.FOCUSER;
                }
                if (e.contains("wheel")) {
                    return DeviceKind.FILTERWHEEL;
                }
            }
        }
        return DeviceKind.UNKNOWN;
    }

    public static DeviceKind classify(Collection<IndiProperty> props) {
        DeviceKind fromDriver = classifyFromDriverInfo(props);
        if (fromDriver != DeviceKind.UNKNOWN) {
            return fromDriver;
        }
        Set<String> names = props.stream().map(IndiProperty::name).collect(Collectors.toSet());
        if (names.stream().anyMatch(MOUNT_HINTS::contains)) {
            return DeviceKind.MOUNT;
        }
        if (names.stream().anyMatch(CAMERA_HINTS::contains)) {
            return DeviceKind.CAMERA;
        }
        if (names.stream().anyMatch(FILTER_HINTS::contains)) {
            return DeviceKind.FILTERWHEEL;
        }
        if (names.stream().anyMatch(FOCUSER_HINTS::contains)) {
            return DeviceKind.FOCUSER;
        }
        return DeviceKind.UNKNOWN;
    }

    public static Device create(
            String indiName,
            Collection<IndiProperty> props,
            IndiClient client,
            EventBus bus,
            CameraImageSink sink) {
        DeviceId id = DeviceId.slug(indiName);
        return switch (classify(props)) {
            case MOUNT -> new IndiMountAdapter(indiName, id, client, bus);
            case CAMERA -> new IndiCameraAdapter(indiName, id, client, bus, sink);
            case FILTERWHEEL -> new IndiFilterWheelAdapter(indiName, id, client, bus);
            case FOCUSER -> new IndiFocuserAdapter(indiName, id, client, bus);
            case UNKNOWN -> null;
        };
    }
}
