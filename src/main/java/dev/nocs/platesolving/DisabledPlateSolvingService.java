package dev.nocs.platesolving;

public class DisabledPlateSolvingService implements PlateSolvingService {

    @Override
    public SolveOutcome solve(byte[] fits, SolveOptions options) {
        return new SolveOutcome.Failed(
                FailureKind.NOT_INSTALLED,
                "Plate solving is disabled (nocs.platesolving.solver=disabled)",
                0L);
    }

    @Override
    public boolean isAvailable() {
        return false;
    }
}
