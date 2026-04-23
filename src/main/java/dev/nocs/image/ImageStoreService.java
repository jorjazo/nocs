package dev.nocs.image;

import dev.nocs.config.NocsProperties;
import dev.nocs.device.DeviceId;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.platesolving.PlateSolutionRecord;
import dev.nocs.platesolving.PlateSolutionRepository;
import dev.nocs.session.Session;
import dev.nocs.session.SessionService;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.Instant;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.SequencedMap;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Service;

@Service
public class ImageStoreService {

    private static final Logger log = LoggerFactory.getLogger(ImageStoreService.class);

    private final ImageRepository repo;
    private final EventBus bus;
    private final ThumbnailGenerator thumbnails;
    private final PendingCaptures pending = new PendingCaptures();
    private final Path dataDir;
    private final ObjectProvider<SessionService> sessionService;
    private final PlateSolutionRepository plateSolutions;

    public ImageStoreService(
            ImageRepository repo,
            EventBus bus,
            ThumbnailGenerator thumbnails,
            NocsProperties props,
            ObjectProvider<SessionService> sessionService,
            PlateSolutionRepository plateSolutions) {
        this.repo = repo;
        this.bus = bus;
        this.thumbnails = thumbnails;
        String dir = props.dataDir() != null ? props.dataDir() : System.getProperty("java.io.tmpdir");
        this.dataDir = Path.of(dir);
        this.sessionService = sessionService;
        this.plateSolutions = plateSolutions;
    }

    public void prepareCapture(DeviceId camera, CaptureContext ctx) {
        pending.prepare(camera, ctx);
    }

    /** Entry point for {@link dev.nocs.device.CameraImageSink} (wired as {@code imageStore::accept} in {@code AppBeansConfig}). */
    public void accept(DeviceId camera, byte[] bytes, String extension) {
        CaptureContext ctx = pending.consume(camera).orElseGet(() -> CaptureContext.defaults(0));
        try {
            saveAndPublish(camera, bytes, extension, ctx);
        } catch (Exception e) {
            log.error("image store failed for camera {}: {}", camera.value(), e.getMessage(), e);
            bus.publish(Event.of(Topic.CAMERA, "image_store_failed", Map.of(
                    "device", camera.value(),
                    "error", e.getMessage() == null ? "unknown" : e.getMessage())));
        }
    }

    private void saveAndPublish(DeviceId camera, byte[] bytes, String extension, CaptureContext ctx)
            throws IOException {
        Path fitsPath = ImagePaths.forCapture(dataDir, LocalDate.now(), camera.value(), ctx);
        Files.createDirectories(fitsPath.getParent());
        fitsPath = ImagePaths.nextAvailable(fitsPath);
        Path tempFile = fitsPath.resolveSibling(fitsPath.getFileName() + ".part");
        Files.write(tempFile, bytes);
        Files.move(tempFile, fitsPath, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);

        Optional<byte[]> thumbBytes = isFits(extension)
                ? thumbnails.generate(bytes)
                : Optional.empty();
        Path thumbPath = null;
        if (thumbBytes.isPresent()) {
            thumbPath = ImagePaths.thumbnailFor(fitsPath);
            Files.write(thumbPath, thumbBytes.get());
        }

        Integer width = null;
        Integer height = null;
        Integer bitpix = null;
        String dateObs = null;
        if (isFits(extension)) {
            try {
                FitsHeaderReader.Header h = FitsHeaderReader.read(bytes);
                width = h.naxis() == 2 ? h.naxis1() : null;
                height = h.naxis() == 2 ? h.naxis2() : null;
                bitpix = h.bitpix();
                dateObs = h.dateObs();
            } catch (IllegalArgumentException e) {
                log.warn("metadata extraction failed for {}: {}", fitsPath, e.getMessage());
            }
        }

        Long sessionId = currentSessionId();
        ImageRecord rec = ImageRecord.forInsert(
                sessionId, camera.value(), ctx,
                fitsPath.toString(),
                thumbPath == null ? null : thumbPath.toString(),
                bytes.length, width, height, bitpix, dateObs);
        long id = repo.insert(rec);

        Map<String, Object> payload = new HashMap<>();
        payload.put("id", id);
        payload.put("device", camera.value());
        payload.put("session_id", sessionId);
        payload.put("fits_path", fitsPath.toString());
        payload.put("thumb_path", thumbPath == null ? null : thumbPath.toString());
        payload.put("filter", ctx.filter());
        payload.put("target", ctx.target());
        payload.put("exposure_s", ctx.exposureSec());
        payload.put("step", ctx.step());
        payload.put("seq", ctx.seq());
        payload.put("bytes", (long) bytes.length);
        payload.put("width", width);
        payload.put("height", height);
        payload.put("bitpix", bitpix);
        payload.put("date_obs", dateObs);
        bus.publish(Event.of(Topic.CAMERA, "image_saved", payload));
    }

    public Optional<ImageRecord> find(long id) {
        return repo.findById(id);
    }

    public List<ImageRecord> list(ImageRepository.Filters filters) {
        return repo.list(filters);
    }

    public boolean delete(long id) {
        Optional<ImageRecord> existing = repo.findById(id);
        if (existing.isEmpty()) {
            return false;
        }
        ImageRecord rec = existing.get();
        deleteIfPresent(Path.of(rec.fitsPath()));
        if (rec.thumbPath() != null) {
            deleteIfPresent(Path.of(rec.thumbPath()));
        }
        return repo.delete(id);
    }

    public Optional<byte[]> loadFits(long id) {
        return find(id).flatMap(rec -> {
            try {
                return Optional.of(Files.readAllBytes(Path.of(rec.fitsPath())));
            } catch (IOException e) {
                log.warn("loadFits failed for id {}: {}", id, e.getMessage());
                return Optional.empty();
            }
        });
    }

    /**
     * Rewrites the saved FITS header with {@code additionalCards}, persisting the bytes
     * atomically and refreshing the {@code images.bytes} count. When the additions look
     * like a WCS solution (presence of {@code CRVAL1} + {@code CRVAL2}), upserts a
     * {@link PlateSolutionRecord} for the image. Returns true when the row was updated.
     */
    public boolean amendHeader(long id, SequencedMap<String, String> additionalCards) {
        Optional<ImageRecord> existing = repo.findById(id);
        if (existing.isEmpty()) {
            return false;
        }
        ImageRecord rec = existing.get();
        Path path = Path.of(rec.fitsPath());
        byte[] original;
        try {
            original = Files.readAllBytes(path);
        } catch (IOException e) {
            log.error("amendHeader cannot read {}: {}", path, e.getMessage());
            return false;
        }
        byte[] amended = FitsHeaderWriter.writeWithCards(original, additionalCards);
        try {
            Path tmp = path.resolveSibling(path.getFileName() + ".amend");
            Files.write(tmp, amended);
            Files.move(tmp, path, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } catch (IOException e) {
            log.error("amendHeader cannot write {}: {}", path, e.getMessage());
            return false;
        }
        repo.updateBytes(id, amended.length);

        if (additionalCards != null
                && additionalCards.containsKey("CRVAL1")
                && additionalCards.containsKey("CRVAL2")) {
            try {
                double ra = Double.parseDouble(additionalCards.get("CRVAL1").trim());
                double dec = Double.parseDouble(additionalCards.get("CRVAL2").trim());
                double pixelScale = additionalCards.containsKey("CDELT2")
                        ? Math.abs(Double.parseDouble(additionalCards.get("CDELT2").trim())) * 3600.0
                        : 0.0;
                double rot = additionalCards.containsKey("CROTA2")
                        ? Double.parseDouble(additionalCards.get("CROTA2").trim())
                        : 0.0;
                double fovW = additionalCards.containsKey("FOVWIDTH")
                        ? Double.parseDouble(additionalCards.get("FOVWIDTH").trim())
                        : 0.0;
                double fovH = additionalCards.containsKey("FOVHIGHT")
                        ? Double.parseDouble(additionalCards.get("FOVHIGHT").trim())
                        : 0.0;
                String solver = additionalCards.containsKey("PLATESLV")
                        ? additionalCards.get("PLATESLV").replace("'", "").trim()
                        : "unknown";
                plateSolutions.upsert(PlateSolutionRecord.forInsert(
                        id, ra, dec, pixelScale, rot, fovW, fovH, 0L, solver, Instant.now()));
            } catch (NumberFormatException e) {
                log.warn("amendHeader: WCS cards present but un-parseable for id {}: {}", id, e.getMessage());
            }
        }
        return true;
    }

    private static boolean isFits(String extension) {
        if (extension == null) {
            return false;
        }
        String e = extension.toLowerCase();
        return e.equals(".fits") || e.equals("fits") || e.endsWith(".fits") || e.endsWith(".fit");
    }

    private Long currentSessionId() {
        SessionService svc = sessionService.getIfAvailable();
        if (svc == null) {
            return null;
        }
        Session s = svc.current();
        return s == null ? null : s.id();
    }

    private static void deleteIfPresent(Path p) {
        try {
            Files.deleteIfExists(p);
        } catch (IOException e) {
            log.warn("failed to delete {}: {}", p, e.getMessage());
        }
    }
}
