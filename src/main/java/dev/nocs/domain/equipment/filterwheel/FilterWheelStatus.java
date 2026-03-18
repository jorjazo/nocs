package dev.nocs.domain.equipment.filterwheel;

/**
 * Current live state of the filter wheel.
 */
public record FilterWheelStatus(
        int currentSlot,
        boolean moving,
        int slotCount
) {
    public FilterWheelStatus {
        if (currentSlot < 0) currentSlot = 0;
        if (slotCount < 1) slotCount = 1;
    }
}
