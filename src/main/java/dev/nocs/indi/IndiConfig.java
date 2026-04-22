package dev.nocs.indi;

import java.util.List;

public record IndiConfig(
        Mode mode,
        String host,
        Integer port,
        List<String> drivers,
        Restart restart) {

    public enum Mode {
        MANAGED,
        EXTERNAL,
        DISABLED
    }

    public record Restart(Long initialBackoffMs, Long maxBackoffMs) {
        public Restart {
            if (initialBackoffMs == null) {
                initialBackoffMs = 500L;
            }
            if (maxBackoffMs == null) {
                maxBackoffMs = 30_000L;
            }
        }
    }

    public IndiConfig {
        if (mode == null) {
            mode = Mode.MANAGED;
        }
        if (host == null || host.isBlank()) {
            host = "127.0.0.1";
        }
        if (port == null) {
            port = 7624;
        }
        if (drivers == null) {
            drivers = List.of();
        }
        if (restart == null) {
            restart = new Restart(null, null);
        }
    }
}
