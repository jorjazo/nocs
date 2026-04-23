package dev.nocs.config;

import dev.nocs.indi.IndiConfig;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "nocs")
public record NocsProperties(
        Auth auth,
        Server server,
        Datasource datasource,
        String dataDir,
        IndiConfig indi,
        Targets targets,
        Safety safety) {

    public record Auth(String token) {}

    public record Server(String host, Integer port) {}

    public record Datasource(String url) {}

    public record Targets(Boolean onlineResolver, String simbadBaseUrl) {
        public Targets {
            if (onlineResolver == null) {
                onlineResolver = false;
            }
            if (simbadBaseUrl == null || simbadBaseUrl.isBlank()) {
                simbadBaseUrl = "https://simbad.u-strasbg.fr/simbad";
            }
        }
    }

    public record Safety(String rulesPath, Long altitudeEvalIntervalMs, Long sensorOfflineDefaultSeconds) {
        public Safety {
            if (altitudeEvalIntervalMs == null || altitudeEvalIntervalMs <= 0) {
                altitudeEvalIntervalMs = 10_000L;
            }
            if (sensorOfflineDefaultSeconds == null || sensorOfflineDefaultSeconds <= 0) {
                sensorOfflineDefaultSeconds = 60L;
            }
        }
    }
}
