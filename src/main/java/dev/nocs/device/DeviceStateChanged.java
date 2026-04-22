package dev.nocs.device;

import java.util.Map;

public record DeviceStateChanged(DeviceId id, DeviceKind kind, String oldState, String newState) {

    public Map<String, Object> toPayload() {
        return Map.of(
                "id", id.value(),
                "kind", kind.name().toLowerCase(),
                "old", oldState,
                "new", newState);
    }
}
