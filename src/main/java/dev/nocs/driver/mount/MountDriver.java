package dev.nocs.driver.mount;

import dev.nocs.domain.equipment.DriverStatus;
import dev.nocs.domain.equipment.mount.MountConfiguration;
import dev.nocs.domain.equipment.mount.MountDriverConfiguration;
import dev.nocs.domain.equipment.mount.MountStatus;

/**
 * Equipment-specific operations for a mount driver.
 */
public interface MountDriver {

    MountStatus getStatus();

    MountConfiguration getConfiguration();

    void setConfiguration(MountConfiguration config);

    DriverStatus getDriverStatus();

    MountDriverConfiguration getDriverConfiguration();

    void setDriverConfiguration(MountDriverConfiguration config);

    void connect();

    void disconnect();

    void gotoPosition(double raHours, double decDegrees);

    void park();

    void sync(double raHours, double decDegrees);

    void startTracking();

    void stopTracking();
}
