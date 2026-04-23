package dev.nocs.platesolving.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

public record InstallStatusView(
        @JsonProperty("installed") boolean installed,
        @JsonProperty("binary_path") String binaryPath,
        @JsonProperty("db_dir") String dbDir,
        @JsonProperty("db_name") String dbName,
        @JsonProperty("db_present") boolean dbPresent,
        @JsonProperty("supported_platform") boolean supportedPlatform,
        @JsonProperty("allow_network") boolean allowNetwork) {}
