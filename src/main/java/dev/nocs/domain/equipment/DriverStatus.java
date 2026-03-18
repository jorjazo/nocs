package dev.nocs.domain.equipment;

/**
 * Connection and driver health status. Common across all equipment types.
 */
public record DriverStatus(
        ConnectionState connectionState,
        String lastError
) {
    public DriverStatus {
        if (connectionState == null) {
            connectionState = ConnectionState.DISCONNECTED;
        }
    }

    public enum ConnectionState {
        CONNECTED,
        CONNECTING,
        DISCONNECTED,
        ERROR
    }
}
