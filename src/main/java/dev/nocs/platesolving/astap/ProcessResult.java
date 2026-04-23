package dev.nocs.platesolving.astap;

public record ProcessResult(int exitCode, String stdout, String stderr, boolean timedOut, long durationMs) {}
