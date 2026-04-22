package dev.nocs.events;

public enum Topic {
    MOUNT, CAMERA, FILTERWHEEL, FOCUSER,
    SEQUENCE, SAFETY, SESSION, DEVICE_CONNECTION, SYSTEM,
    TARGET;

    public String wire() {
        return name().toLowerCase();
    }

    public static Topic fromWire(String wire) {
        return Topic.valueOf(wire.trim().toUpperCase());
    }
}
