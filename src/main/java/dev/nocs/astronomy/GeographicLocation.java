package dev.nocs.astronomy;

/** Observer location; east longitude positive. */
public record GeographicLocation(double latitudeDeg, double longitudeDeg, double elevationM) {}
