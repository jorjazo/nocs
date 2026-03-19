package dev.nocs.service;

import java.time.Instant;

/**
 * Metadata captured alongside an exposure for FITS headers and API responses.
 */
public record ImageMetadata(
        String cameraName,
        int gain,
        int offset,
        double exposureSeconds,
        double temperatureCelsius,
        int binning,
        int width,
        int height,
        int bitDepth,
        double pixelSizeMicrons,
        Instant dateObs
) {}
