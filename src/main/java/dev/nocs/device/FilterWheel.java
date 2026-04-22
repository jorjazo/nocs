package dev.nocs.device;

import java.util.List;

public interface FilterWheel extends Device {

    FilterWheelState state();

    List<String> slotNames();

    int currentSlot();

    void selectSlot(int slot);

    @Override
    default DeviceKind kind() {
        return DeviceKind.FILTERWHEEL;
    }
}
