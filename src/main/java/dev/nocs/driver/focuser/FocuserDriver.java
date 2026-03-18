package dev.nocs.driver.focuser;

import dev.nocs.domain.equipment.DriverStatus;
import dev.nocs.domain.equipment.focuser.FocuserConfiguration;
import dev.nocs.domain.equipment.focuser.FocuserDriverConfiguration;
import dev.nocs.domain.equipment.focuser.FocuserStatus;

/**
 * Equipment-specific operations for a focuser driver.
 */
public interface FocuserDriver {

    FocuserStatus getStatus();

    FocuserConfiguration getConfiguration();

    void setConfiguration(FocuserConfiguration config);

    DriverStatus getDriverStatus();

    FocuserDriverConfiguration getDriverConfiguration();

    void setDriverConfiguration(FocuserDriverConfiguration config);

    void connect();

    void disconnect();

    void moveRelative(int steps);

    void moveAbsolute(int position);
}
