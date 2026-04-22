package dev.nocs.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "nocs")
public record NocsProperties(Auth auth, Server server, Datasource datasource, String dataDir) {
    public record Auth(String token) {}
    public record Server(String host, Integer port) {}
    public record Datasource(String url) {}
}
