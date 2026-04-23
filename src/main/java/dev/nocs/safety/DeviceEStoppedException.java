package dev.nocs.safety;

public class DeviceEStoppedException extends RuntimeException {

    public DeviceEStoppedException(String deviceId) {
        super("device " + deviceId + " is e-stopped; reset via POST /api/safety/reset before issuing commands");
    }
}
