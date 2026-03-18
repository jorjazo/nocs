package dev.nocs.domain.equipment.focuser;

/**
 * Equipment-level focuser settings.
 */
public record FocuserConfiguration(
        int maxPosition,
        int stepSize
) {
    public FocuserConfiguration {
        if (maxPosition <= 0) maxPosition = 50000;
        if (stepSize <= 0) stepSize = 1;
    }
}
