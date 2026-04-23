package dev.nocs.config;

import dev.nocs.indi.IndiConfig;
import java.util.Map;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "nocs")
public record NocsProperties(
        Auth auth,
        Server server,
        Datasource datasource,
        String dataDir,
        IndiConfig indi,
        Targets targets,
        Safety safety,
        PlateSolving platesolving) {

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

    public record PlateSolving(
            String solver,
            Long solveTimeoutSec,
            Astap astap,
            Install install) {

        public PlateSolving {
            if (solver == null || solver.isBlank()) {
                solver = "astap";
            }
            if (solveTimeoutSec == null || solveTimeoutSec <= 0) {
                solveTimeoutSec = 60L;
            }
            if (astap == null) {
                astap = new Astap(null, null, null);
            }
            if (install == null) {
                install = new Install(false, null, Map.of(), null, null);
            }
        }

        public record Astap(String binaryPath, String dbDir, String dbName) {
            public Astap {
                if (dbName == null || dbName.isBlank()) {
                    dbName = "H18";
                }
            }
        }

        public record Install(
                Boolean allowNetwork,
                String binaryUrlTemplate,
                Map<String, String> binarySha256,
                String dbUrl,
                String dbSha256) {

            public Install {
                if (allowNetwork == null) {
                    allowNetwork = false;
                }
                if (binarySha256 == null) {
                    binarySha256 = Map.of();
                }
            }
        }
    }
}
