package dev.nocs.device;

public record DeviceId(String value) {

    public DeviceId {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("device id is blank");
        }
    }

    public static DeviceId slug(String indiName) {
        if (indiName == null || indiName.isBlank()) {
            throw new IllegalArgumentException("indi device name is blank");
        }
        String s = indiName.trim()
                .toLowerCase()
                .replaceAll("[^a-z0-9]+", "-")
                .replaceAll("^-|-$", "");
        return new DeviceId(s);
    }
}
