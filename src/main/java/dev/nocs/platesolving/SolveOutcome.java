package dev.nocs.platesolving;

public sealed interface SolveOutcome permits SolveOutcome.Solved, SolveOutcome.Failed {

    long durationMs();

    record Solved(PlateSolution solution, long durationMs) implements SolveOutcome {
        public Solved {
            if (solution == null) {
                throw new IllegalArgumentException("solution required");
            }
        }
    }

    record Failed(FailureKind kind, String message, long durationMs) implements SolveOutcome {
        public Failed {
            if (kind == null) {
                throw new IllegalArgumentException("kind required");
            }
            if (message == null) {
                message = "";
            }
        }
    }
}
