package dev.nocs.image;

import dev.nocs.config.NocsProperties;
import dev.nocs.device.DeviceId;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import dev.nocs.session.Session;
import dev.nocs.session.SessionService;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
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

    public ImageStoreService(
            ImageRepository repo,
            EventBus bus,
            ThumbnailGenerator thumbnails,
            NocsProperties props,
            ObjectProvider<SessionService> sessionService) {
        this.repo = repo;
        this.bus = bus;
        this.thumbnails = thumbnails;
        String dir = props.dataDir() != null ? props.dataDir() : System.getProperty("java.io.tmpdir");
        this.dataDir = Path.of(dir);
        this.sessionService = sessionService;
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

    /**
     * Stub for Plan E: plate solver will amend the saved FITS header (RA/Dec/scale/rotation) and
     * re-derive width/height/dateObs in the row. v0.1 (Plan D) does not implement amendment.
     */
    public void amendHeader(long id, Map<String, String> additionalCards) {
        log.debug("amendHeader stub called for id={} (cards={}), no-op in Plan D", id, additionalCards);
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
