package dev.nocs.target.api.dto;

import dev.nocs.target.Target;
import dev.nocs.target.TargetKind;
import java.util.List;

public record TargetView(
        String id,
        String primaryName,
        List<String> aliases,
        TargetKind kind,
        double raJ2000Deg,
        double decJ2000Deg,
        String constellation,
        double magnitude,
        double sizeArcmin,
        String notes) {

    public static TargetView of(Target t) {
        return new TargetView(
                t.id(),
                t.primaryName(),
                t.aliases(),
                t.kind(),
                t.raJ2000Deg(),
                t.decJ2000Deg(),
                t.constellation(),
                t.magnitude(),
                t.sizeArcmin(),
                t.notes());
    }
}
