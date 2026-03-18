package dev.nocs.driver;

import dev.nocs.domain.Driver;
import dev.nocs.domain.LogicalDevice;

import java.util.List;

/**
 * Interface for equipment drivers. Drivers must be loaded before they provide
 * logical devices. When unloaded, getLogicalDevices() returns an empty list.
 */
public interface EquipmentDriver {

    /**
     * Driver metadata (id, displayName, description, version, etc.).
     */
    Driver getMetadata();

    /**
     * Load the driver. After loading, hardware discovery runs and
     * getLogicalDevices() may return devices.
     */
    void load();

    /**
     * Unload the driver. After unloading, getLogicalDevices() returns empty.
     */
    void unload();

    /**
     * Whether this driver is currently loaded.
     */
    boolean isLoaded();

    /**
     * Logical devices this driver provides at runtime. Returns empty when
     * the driver is not loaded.
     */
    List<LogicalDevice> getLogicalDevices();
}
