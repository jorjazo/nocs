package dev.nocs.domain.equipment.focuser;

/**
 * Current live state of the focuser.
 */
public record FocuserStatus(
        int position,
        boolean moving,
        Double temperatureCelsius
) {
    public FocuserStatus {
        if (position < 0) position = 0;
        if (temperatureCelsius == null) temperatureCelsius = 20.0;
    }
}
