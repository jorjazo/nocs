package dev.nocs.image.api;

import dev.nocs.image.ImageRecord;
import dev.nocs.image.ImageRepository;
import dev.nocs.image.ImageStoreService;
import dev.nocs.image.api.dto.ImageView;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Optional;
import org.springframework.core.io.FileSystemResource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/images")
public class ImageController {

    public static final MediaType FITS_TYPE = MediaType.parseMediaType("application/fits");

    private final ImageStoreService store;

    public ImageController(ImageStoreService store) {
        this.store = store;
    }

    @GetMapping
    public List<ImageView> list(
            @RequestParam(value = "device", required = false) String device,
            @RequestParam(value = "session_id", required = false) Long sessionId,
            @RequestParam(value = "target", required = false) String target,
            @RequestParam(value = "filter", required = false) String filter,
            @RequestParam(value = "limit", defaultValue = "100") int limit,
            @RequestParam(value = "offset", defaultValue = "0") int offset) {
        return store.list(new ImageRepository.Filters(device, sessionId, target, filter, limit, offset))
                .stream().map(ImageView::from).toList();
    }

    @GetMapping("/{id}")
    public ResponseEntity<ImageView> get(@PathVariable long id) {
        return store.find(id)
                .map(r -> ResponseEntity.ok(ImageView.from(r)))
                .orElse(ResponseEntity.notFound().build());
    }

    @GetMapping("/{id}.fits")
    public ResponseEntity<?> downloadFits(@PathVariable long id) throws IOException {
        Optional<ImageRecord> rec = store.find(id);
        if (rec.isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        Path path = Path.of(rec.get().fitsPath());
        if (!Files.exists(path)) {
            return ResponseEntity.notFound().build();
        }
        HttpHeaders headers = new HttpHeaders();
        headers.set(HttpHeaders.CONTENT_DISPOSITION,
                "attachment; filename=\"" + path.getFileName().toString() + "\"");
        return ResponseEntity.ok()
                .headers(headers)
                .contentType(FITS_TYPE)
                .contentLength(Files.size(path))
                .body(new FileSystemResource(path));
    }

    @GetMapping("/{id}/thumb.jpg")
    public ResponseEntity<?> downloadThumb(@PathVariable long id) throws IOException {
        Optional<ImageRecord> rec = store.find(id);
        if (rec.isEmpty() || rec.get().thumbPath() == null) {
            return ResponseEntity.notFound().build();
        }
        Path path = Path.of(rec.get().thumbPath());
        if (!Files.exists(path)) {
            return ResponseEntity.notFound().build();
        }
        return ResponseEntity.ok()
                .contentType(MediaType.IMAGE_JPEG)
                .contentLength(Files.size(path))
                .body(new FileSystemResource(path));
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<Void> delete(@PathVariable long id) {
        boolean removed = store.delete(id);
        return removed ? ResponseEntity.noContent().build() : ResponseEntity.notFound().build();
    }
}
