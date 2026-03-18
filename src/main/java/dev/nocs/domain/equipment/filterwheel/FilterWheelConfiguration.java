package dev.nocs.domain.equipment.filterwheel;

import java.util.List;

/**
 * Equipment-level filter wheel settings (filter names per slot).
 */
public record FilterWheelConfiguration(
        List<String> filterNames
) {
    public FilterWheelConfiguration {
        if (filterNames == null) filterNames = List.of();
    }
}
