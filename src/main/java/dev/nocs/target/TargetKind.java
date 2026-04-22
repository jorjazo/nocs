package dev.nocs.target;

public enum TargetKind {
    GALAXY,
    NEBULA,
    CLUSTER_OPEN,
    CLUSTER_GLOBULAR,
    PLANETARY_NEBULA,
    DARK_NEBULA,
    DOUBLE_STAR,
    ASTERISM,
    STAR,
    PLANET,
    SUN,
    MOON,
    CUSTOM,
    OTHER;

    public static TargetKind parseOrOther(String s) {
        if (s == null) return OTHER;
        try {
            return TargetKind.valueOf(s.trim().toUpperCase());
        } catch (IllegalArgumentException e) {
            return OTHER;
        }
    }
}
