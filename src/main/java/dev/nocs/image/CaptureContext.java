package dev.nocs.image;

public record CaptureContext(
        String filter,
        String target,
        double exposureSec,
        String step,
        int seq) {

    public CaptureContext {
        if (exposureSec < 0) {
            throw new IllegalArgumentException("exposureSec must be >= 0, got " + exposureSec);
        }
        if (filter == null || filter.isBlank()) {
            filter = "UNK";
        }
        if (target == null || target.isBlank()) {
            target = "untargeted";
        }
        if (step == null) {
            step = "";
        }
        if (seq < 0) {
            seq = 0;
        }
    }

    public static CaptureContext defaults(double exposureSec) {
        return new CaptureContext(null, null, exposureSec, null, 0);
    }
}
