package dev.nocs.platesolving.install;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonProperty;

public record InstallRequest(
        @JsonProperty("accept_license") @JsonAlias("acceptLicense") boolean acceptLicense) {}
