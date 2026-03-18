package dev.nocs.events;

import dev.nocs.domain.events.EquipmentConnected;
import dev.nocs.domain.events.EquipmentDisconnected;
import dev.nocs.domain.events.EquipmentStatusChanged;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

/**
 * Listens for equipment events and broadcasts them to SSE clients.
 */
@Component
public class EquipmentEventListener {

    private final EquipmentSseBroadcaster broadcaster;

    public EquipmentEventListener(EquipmentSseBroadcaster broadcaster) {
        this.broadcaster = broadcaster;
    }

    @EventListener
    public void onEquipmentStatusChanged(EquipmentStatusChanged event) {
        broadcaster.broadcast(event);
    }

    @EventListener
    public void onEquipmentConnected(EquipmentConnected event) {
        broadcaster.broadcast(event);
    }

    @EventListener
    public void onEquipmentDisconnected(EquipmentDisconnected event) {
        broadcaster.broadcast(event);
    }
}
