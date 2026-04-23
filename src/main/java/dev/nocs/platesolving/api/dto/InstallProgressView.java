package dev.nocs.platesolving.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import dev.nocs.platesolving.install.InstallProgress;
import java.time.Instant;

public record InstallProgressView(
        @JsonProperty("phase") String phase,
        @JsonProperty("bytes_done") long bytesDone,
        @JsonProperty("bytes_total") long bytesTotal,
        @JsonProperty("message") String message,
        @JsonProperty("updated_at") Instant updatedAt) {

    public static InstallProgressView from(InstallProgress p) {
        return new InstallProgressView(
                p.phase().name().toLowerCase(), p.bytesDone(), p.bytesTotal(), p.message(), p.updatedAt());
    }
}
