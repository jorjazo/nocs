package dev.nocs.platesolving;

public enum FailureKind {
    NOT_INSTALLED,
    NO_STARS,
    TIMEOUT,
    IO_ERROR,
    INTERNAL_ERROR;

    public String wire() {
        return name().toLowerCase();
    }
}
