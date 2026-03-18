package dev.nocs.domain.equipment.mount;

/**
 * Equipment-level mount settings (how the device operates).
 */
public record MountConfiguration(
        double slewRateDegPerSec,
        double guideRateArcsecPerSec,
        boolean meridianFlipEnabled,
        double meridianFlipLimitDegrees
) {
    public MountConfiguration {
        if (slewRateDegPerSec <= 0) slewRateDegPerSec = 2.0;
        if (guideRateArcsecPerSec <= 0) guideRateArcsecPerSec = 0.5;
        if (meridianFlipLimitDegrees <= 0) meridianFlipLimitDegrees = 5.0;
    }
}
