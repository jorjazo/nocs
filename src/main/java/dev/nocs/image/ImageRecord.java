package dev.nocs.image;

import java.time.Instant;

public record ImageRecord(
        Long id,
        Long sessionId,
        String deviceId,
        String filter,
        String target,
        double exposureSec,
        String stepName,
        int seqIndex,
        String fitsPath,
        String thumbPath,
        long bytes,
        Integer width,
        Integer height,
        Integer bitpix,
        String dateObs,
        Instant createdAt) {

    public static ImageRecord forInsert(
            Long sessionId,
            String deviceId,
            CaptureContext ctx,
            String fitsPath,
            String thumbPath,
            long bytes,
            Integer width,
            Integer height,
            Integer bitpix,
            String dateObs) {
        return new ImageRecord(
                null, sessionId, deviceId,
                ctx.filter(), ctx.target(), ctx.exposureSec(), ctx.step(), ctx.seq(),
                fitsPath, thumbPath, bytes, width, height, bitpix, dateObs, null);
    }
}
