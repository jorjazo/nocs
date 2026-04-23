package dev.nocs.platesolving.install;

import java.time.Instant;

public record InstallProgress(
        InstallPhase phase, long bytesDone, long bytesTotal, String message, Instant updatedAt) {

    public InstallProgress {
        if (phase == null) {
            phase = InstallPhase.IDLE;
        }
        if (message == null) {
            message = "";
        }
        if (updatedAt == null) {
            updatedAt = Instant.now();
        }
    }

    public static InstallProgress idle() {
        return new InstallProgress(InstallPhase.IDLE, 0L, 0L, "", Instant.now());
    }
}
