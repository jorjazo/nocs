package dev.nocs.driver.filterwheel;

import dev.nocs.domain.equipment.DriverStatus;
import dev.nocs.domain.equipment.filterwheel.FilterWheelConfiguration;
import dev.nocs.domain.equipment.filterwheel.FilterWheelDriverConfiguration;
import dev.nocs.domain.equipment.filterwheel.FilterWheelStatus;

/**
 * Equipment-specific operations for a filter wheel driver.
 */
public interface FilterWheelDriver {

    FilterWheelStatus getStatus();

    FilterWheelConfiguration getConfiguration();

    void setConfiguration(FilterWheelConfiguration config);

    DriverStatus getDriverStatus();

    FilterWheelDriverConfiguration getDriverConfiguration();

    void setDriverConfiguration(FilterWheelDriverConfiguration config);

    void connect();

    void disconnect();

    void selectSlot(int slot);
}
