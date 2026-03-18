package dev.nocs.domain.equipment.camera;

/**
 * Equipment-level camera settings.
 */
public record CameraConfiguration(
        int gain,
        int offset,
        int binning,
        int roiX,
        int roiY,
        int roiWidth,
        int roiHeight
) {
    public CameraConfiguration {
        if (gain < 0) gain = 0;
        if (offset < 0) offset = 0;
        if (binning < 1) binning = 1;
        if (roiX < 0) roiX = 0;
        if (roiY < 0) roiY = 0;
        if (roiWidth < 1) roiWidth = 1;
        if (roiHeight < 1) roiHeight = 1;
    }
}
