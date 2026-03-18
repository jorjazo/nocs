package dev.nocs.domain.events;

import dev.nocs.domain.EquipmentType;

/**
 * Event emitted when a driver disconnects (profile unload, connection lost, error).
 */
public record EquipmentDisconnected(
        EquipmentType equipmentType,
        String reason
) {
    public EquipmentDisconnected(EquipmentType equipmentType) {
        this(equipmentType, null);
    }
}
