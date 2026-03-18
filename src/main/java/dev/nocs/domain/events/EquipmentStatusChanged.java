package dev.nocs.domain.events;

import dev.nocs.domain.EquipmentType;
import dev.nocs.domain.equipment.DriverStatus;

/**
 * Event emitted when equipment status changes. The status payload is the
 * equipment-specific status object (e.g. MountStatus, CameraStatus).
 */
public record EquipmentStatusChanged(
        EquipmentType equipmentType,
        Object statusPayload,
        DriverStatus driverStatus
) {
    public EquipmentStatusChanged(EquipmentType equipmentType, Object statusPayload) {
        this(equipmentType, statusPayload, null);
    }
}
