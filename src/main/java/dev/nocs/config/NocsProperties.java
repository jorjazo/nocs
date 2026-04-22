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
        Targets targets) {

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
}
