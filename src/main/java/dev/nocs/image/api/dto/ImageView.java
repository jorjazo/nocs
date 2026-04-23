package dev.nocs.image.api.dto;

import dev.nocs.image.ImageRecord;
import java.time.Instant;

public record ImageView(
        long id,
        Long sessionId,
        String device,
        String filter,
        String target,
        double exposureSec,
        String step,
        int seq,
        String fitsPath,
        String thumbPath,
        long bytes,
        Integer width,
        Integer height,
        Integer bitpix,
        String dateObs,
        Instant createdAt) {

    public static ImageView from(ImageRecord r) {
        return new ImageView(
                r.id(), r.sessionId(), r.deviceId(),
                r.filter(), r.target(), r.exposureSec(), r.stepName(), r.seqIndex(),
                r.fitsPath(), r.thumbPath(),
                r.bytes(), r.width(), r.height(), r.bitpix(), r.dateObs(),
                r.createdAt());
    }
}
