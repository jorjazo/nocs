package dev.nocs.domain.events;

import dev.nocs.domain.EquipmentType;
import dev.nocs.domain.equipment.DriverStatus;

/**
 * Event emitted when a driver successfully connects to hardware
 * (or simulator becomes "connected").
 */
public record EquipmentConnected(
        EquipmentType equipmentType,
        DriverStatus driverStatus
) {
    public EquipmentConnected(EquipmentType equipmentType) {
        this(equipmentType, null);
    }
}
