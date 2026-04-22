package dev.nocs.indi;

public record PropertyUpdate(Kind kind, IndiProperty property) {

    public enum Kind {
        DEFINED,
        SET,
        DELETED
    }
}
