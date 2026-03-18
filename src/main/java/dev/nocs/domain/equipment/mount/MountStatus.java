package dev.nocs.domain.equipment.mount;

/**
 * Current live state of the mount.
 */
public record MountStatus(
        double raHours,
        double decDegrees,
        boolean tracking,
        boolean slewing,
        boolean parked
) {}
