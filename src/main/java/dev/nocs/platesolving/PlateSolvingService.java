package dev.nocs.platesolving;

public interface PlateSolvingService {

    SolveOutcome solve(byte[] fits, SolveOptions options);

    boolean isAvailable();
}
