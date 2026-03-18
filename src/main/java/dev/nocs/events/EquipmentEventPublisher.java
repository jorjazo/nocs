package dev.nocs.events;

import dev.nocs.domain.EquipmentType;
import dev.nocs.domain.equipment.DriverStatus;
import dev.nocs.domain.events.EquipmentConnected;
import dev.nocs.domain.events.EquipmentDisconnected;
import dev.nocs.domain.events.EquipmentStatusChanged;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Component;

/**
 * Facade for publishing equipment events. Used by drivers and services.
 */
@Component
public class EquipmentEventPublisher {

    private final ApplicationEventPublisher applicationEventPublisher;

    public EquipmentEventPublisher(ApplicationEventPublisher applicationEventPublisher) {
        this.applicationEventPublisher = applicationEventPublisher;
    }

    public void publishStatusChanged(EquipmentType equipmentType, Object status) {
        applicationEventPublisher.publishEvent(new EquipmentStatusChanged(equipmentType, status));
    }

    public void publishStatusChanged(EquipmentType equipmentType, Object status, DriverStatus driverStatus) {
        applicationEventPublisher.publishEvent(new EquipmentStatusChanged(equipmentType, status, driverStatus));
    }

    public void publishConnected(EquipmentType equipmentType) {
        applicationEventPublisher.publishEvent(new EquipmentConnected(equipmentType));
    }

    public void publishConnected(EquipmentType equipmentType, DriverStatus driverStatus) {
        applicationEventPublisher.publishEvent(new EquipmentConnected(equipmentType, driverStatus));
    }

    public void publishDisconnected(EquipmentType equipmentType) {
        applicationEventPublisher.publishEvent(new EquipmentDisconnected(equipmentType));
    }

    public void publishDisconnected(EquipmentType equipmentType, String reason) {
        applicationEventPublisher.publishEvent(new EquipmentDisconnected(equipmentType, reason));
    }
}
