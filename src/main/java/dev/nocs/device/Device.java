package dev.nocs.device;

public interface Device {

    DeviceId id();

    String indiName();

    DeviceKind kind();

    boolean isConnected();

    void connect();

    void disconnect();

    /**
     * Trigger an emergency-stop on this device. Default is a no-op for device kinds whose state machines
     * do not include E_STOPPED (FilterWheel, Focuser). Mount and Camera adapters override this to abort
     * any in-flight motion/exposure and transition to E_STOPPED, after which command methods MUST throw
     * {@link dev.nocs.safety.DeviceEStoppedException} until {@link #resetEStop()} is called.
     */
    default void emergencyStop() {
        // no-op for device kinds without an E_STOPPED state
    }

    /**
     * Clear E_STOPPED on this device. Default is a no-op. Mount/Camera adapters override to transition
     * back to IDLE so command methods stop throwing {@link dev.nocs.safety.DeviceEStoppedException}.
     */
    default void resetEStop() {
        // no-op for device kinds without an E_STOPPED state
    }
}
