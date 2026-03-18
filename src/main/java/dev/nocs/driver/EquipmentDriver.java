package dev.nocs.driver;

import dev.nocs.domain.Driver;
import dev.nocs.domain.LogicalDevice;

import java.util.List;

/**
 * Interface for equipment drivers. Drivers report their metadata and
 * logical devices at runtime. Phase 0: no simulators or real hardware—
 * drivers return metadata and may return empty device lists.
 */
public interface EquipmentDriver {

    /**
     * Driver metadata (id, displayName, description, version, etc.).
     */
    Driver getMetadata();

    /**
     * Logical devices this driver provides at runtime. May be empty when
     * no hardware is connected or in Phase 0 stub mode.
     */
    List<LogicalDevice> getLogicalDevices();
}
