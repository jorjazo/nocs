package dev.nocs.target;

public final class TargetId {

    private TargetId() {}

    public static Parsed parse(String id) {
        if (id == null || id.isBlank()) {
            throw new IllegalArgumentException("target id must not be blank");
        }
        int colon = id.indexOf(':');
        if (colon < 1 || colon == id.length() - 1) {
            throw new IllegalArgumentException("target id must be 'catalog:designator', got: " + id);
        }
        String catalog = id.substring(0, colon).toLowerCase();
        String designator = id.substring(colon + 1).trim();
        if (designator.isEmpty()) {
            throw new IllegalArgumentException("target id designator is blank");
        }
        return new Parsed(catalog, designator);
    }

    public record Parsed(String catalog, String designator) {
        public String format() {
            return catalog + ":" + designator;
        }
    }
}
