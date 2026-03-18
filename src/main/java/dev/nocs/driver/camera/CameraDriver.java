package dev.nocs.driver.camera;

import dev.nocs.domain.equipment.DriverStatus;
import dev.nocs.domain.equipment.camera.CameraConfiguration;
import dev.nocs.domain.equipment.camera.CameraDriverConfiguration;
import dev.nocs.domain.equipment.camera.CameraStatus;

/**
 * Equipment-specific operations for a camera driver.
 */
public interface CameraDriver {

    CameraStatus getStatus();

    CameraConfiguration getConfiguration();

    void setConfiguration(CameraConfiguration config);

    DriverStatus getDriverStatus();

    CameraDriverConfiguration getDriverConfiguration();

    void setDriverConfiguration(CameraDriverConfiguration config);

    void connect();

    void disconnect();

    /**
     * Start an exposure. Returns immediately; status exposes=true until done.
     *
     * @param durationSeconds exposure duration in seconds
     * @return frame id to retrieve the image when done
     */
    String startExposure(double durationSeconds);

    /**
     * Get image data for a completed exposure. Returns placeholder for simulator.
     */
    byte[] getImage(String frameId);
}
