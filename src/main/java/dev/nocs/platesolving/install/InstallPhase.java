package dev.nocs.platesolving.install;

public enum InstallPhase {
    IDLE,
    RESOLVING_SPEC,
    DOWNLOADING_BINARY,
    VERIFYING_BINARY,
    EXTRACTING_BINARY,
    DOWNLOADING_DB,
    VERIFYING_DB,
    EXTRACTING_DB,
    DONE,
    FAILED,
    CANCELLED
}
