package dev.nocs.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import javax.imageio.IIOImage;
import javax.imageio.ImageIO;
import javax.imageio.ImageWriteParam;
import javax.imageio.stream.MemoryCacheImageOutputStream;
import java.awt.image.BufferedImage;
import java.awt.image.DataBufferByte;
import java.io.*;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.Arrays;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Persists the latest exposure to the filesystem as FITS (full quality) and
 * JPEG (lightweight preview). Only the most recent exposure is kept.
 */
@Service
public class ImageStorageService {

    private static final Logger log = LoggerFactory.getLogger(ImageStorageService.class);
    private static final int FITS_BLOCK = 2880;
    private static final int FITS_CARD = 80;
    private static final DateTimeFormatter FITS_DATE = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss");

    private final Path storageDir;
    private final AtomicReference<StoredExposure> latest = new AtomicReference<>();

    record StoredExposure(String frameId, ImageMetadata metadata) {}

    public ImageStorageService(@Value("${nocs.images.storage-path:}") String storagePath) {
        if (storagePath != null && !storagePath.isBlank()) {
            this.storageDir = Path.of(storagePath);
        } else {
            this.storageDir = Path.of(System.getProperty("java.io.tmpdir"), "nocs", "images");
        }
        try {
            Files.createDirectories(this.storageDir);
            log.info("Image storage directory: {}", this.storageDir);
        } catch (IOException e) {
            log.error("Failed to create image storage directory: {}", this.storageDir, e);
        }
    }

    /**
     * Save a completed exposure. Writes FITS and JPEG preview to disk, replacing any previous.
     *
     * @param frameId  unique frame identifier
     * @param rawData  RAW16 image data (unsigned 16-bit, little-endian)
     * @param metadata exposure metadata for FITS headers
     */
    public void saveExposure(String frameId, byte[] rawData, ImageMetadata metadata) {
        try {
            writeFits(rawData, metadata);
            writePreviewJpeg(rawData, metadata.width(), metadata.height());
            latest.set(new StoredExposure(frameId, metadata));
            log.info("Saved exposure {} ({}x{}, FITS + JPEG)", frameId, metadata.width(), metadata.height());
        } catch (Exception e) {
            log.error("Failed to save exposure {}", frameId, e);
        }
    }

    public byte[] getPreviewBytes() {
        Path preview = storageDir.resolve("latest-preview.jpg");
        if (!Files.exists(preview)) return null;
        try {
            return Files.readAllBytes(preview);
        } catch (IOException e) {
            log.error("Failed to read preview", e);
            return null;
        }
    }

    public byte[] getFitsBytes() {
        Path fits = storageDir.resolve("latest.fits");
        if (!Files.exists(fits)) return null;
        try {
            return Files.readAllBytes(fits);
        } catch (IOException e) {
            log.error("Failed to read FITS", e);
            return null;
        }
    }

    public StoredExposure getLatest() {
        return latest.get();
    }

    public boolean hasImage() {
        return latest.get() != null && Files.exists(storageDir.resolve("latest-preview.jpg"));
    }

    // --- FITS writer ---

    private void writeFits(byte[] rawData, ImageMetadata meta) throws IOException {
        int width = meta.width();
        int height = meta.height();

        var cards = new StringBuilder();
        appendCard(cards, "SIMPLE", "T", "FITS standard");
        appendCard(cards, "BITPIX", "16", "16-bit signed integers");
        appendCard(cards, "NAXIS", "2", "2-dimensional image");
        appendCardInt(cards, "NAXIS1", width, "Image width [pixels]");
        appendCardInt(cards, "NAXIS2", height, "Image height [pixels]");
        appendCardFloat(cards, "BZERO", 32768.0, "Offset for unsigned 16-bit");
        appendCardFloat(cards, "BSCALE", 1.0, "Scale factor");
        appendCardInt(cards, "DATAMIN", 0, "Minimum data value");
        appendCardInt(cards, "DATAMAX", 65535, "Maximum data value");
        appendCardFloat(cards, "EXPTIME", meta.exposureSeconds(), "Exposure time [seconds]");
        appendCardInt(cards, "GAIN", meta.gain(), "Camera gain");
        appendCardInt(cards, "OFFSET", meta.offset(), "Camera offset");
        appendCardFloat(cards, "CCD-TEMP", meta.temperatureCelsius(), "CCD temperature [Celsius]");
        appendCardInt(cards, "XBINNING", meta.binning(), "X binning");
        appendCardInt(cards, "YBINNING", meta.binning(), "Y binning");
        if (meta.pixelSizeMicrons() > 0) {
            appendCardFloat(cards, "PIXSIZE1", meta.pixelSizeMicrons() * meta.binning(), "Pixel size X [microns]");
            appendCardFloat(cards, "PIXSIZE2", meta.pixelSizeMicrons() * meta.binning(), "Pixel size Y [microns]");
        }
        appendCardString(cards, "DATE-OBS",
                meta.dateObs().atZone(ZoneOffset.UTC).format(FITS_DATE), "Observation UTC date/time");
        appendCardString(cards, "INSTRUME", meta.cameraName(), "Camera name");
        appendCardString(cards, "SOFTWARE", "NOCS Observatory Control", "Software");
        appendEnd(cards);

        byte[] headerBytes = padToBlock(cards.toString().getBytes(java.nio.charset.StandardCharsets.US_ASCII));

        long pixelCount = (long) width * height;
        byte[] dataBytes = new byte[(int) (pixelCount * 2)];
        ByteBuffer src = ByteBuffer.wrap(rawData).order(ByteOrder.LITTLE_ENDIAN);
        ByteBuffer dst = ByteBuffer.wrap(dataBytes).order(ByteOrder.BIG_ENDIAN);
        for (int i = 0; i < pixelCount; i++) {
            int unsigned = src.getShort() & 0xFFFF;
            dst.putShort((short) (unsigned - 32768));
        }

        byte[] paddedData = padToBlock(dataBytes);

        Path fitsPath = storageDir.resolve("latest.fits");
        try (var fos = new FileOutputStream(fitsPath.toFile())) {
            fos.write(headerBytes);
            fos.write(paddedData);
        }
    }

    private static void appendCard(StringBuilder sb, String keyword, String value, String comment) {
        sb.append(String.format("%-8s= %20s / %-47s", keyword, value, comment));
    }

    private static void appendCardInt(StringBuilder sb, String keyword, int value, String comment) {
        appendCard(sb, keyword, Integer.toString(value), comment);
    }

    private static void appendCardFloat(StringBuilder sb, String keyword, double value, String comment) {
        String v = value == (long) value
                ? String.format("%.1f", value)
                : String.format("%.6f", value);
        if (v.length() > 20) v = v.substring(0, 20);
        appendCard(sb, keyword, v, comment);
    }

    private static void appendCardString(StringBuilder sb, String keyword, String value, String comment) {
        String quoted = "'" + value + "'";
        if (quoted.length() > 20) quoted = quoted.substring(0, 19) + "'";
        sb.append(String.format("%-8s= %-20s / %-47s", keyword, quoted, comment));
    }

    private static void appendEnd(StringBuilder sb) {
        sb.append(String.format("%-80s", "END"));
    }

    private static byte[] padToBlock(byte[] data) {
        int remainder = data.length % FITS_BLOCK;
        if (remainder == 0) return data;
        byte[] padded = Arrays.copyOf(data, data.length + (FITS_BLOCK - remainder));
        return padded;
    }

    // --- JPEG preview ---

    private void writePreviewJpeg(byte[] rawData, int width, int height) throws IOException {
        int pixelCount = width * height;
        if (rawData.length < pixelCount * 2) {
            log.warn("Raw data too short for {}x{} RAW16 image", width, height);
            return;
        }

        int[] values = new int[pixelCount];
        ByteBuffer buf = ByteBuffer.wrap(rawData).order(ByteOrder.LITTLE_ENDIAN);
        for (int i = 0; i < pixelCount; i++) {
            values[i] = buf.getShort() & 0xFFFF;
        }

        int low, high;
        int sampleSize = Math.min(pixelCount, 200_000);
        int[] sample = new int[sampleSize];
        if (sampleSize == pixelCount) {
            System.arraycopy(values, 0, sample, 0, pixelCount);
        } else {
            int step = pixelCount / sampleSize;
            for (int i = 0; i < sampleSize; i++) {
                sample[i] = values[i * step];
            }
        }
        Arrays.sort(sample);
        low = sample[(int) (sampleSize * 0.02)];
        high = sample[(int) (sampleSize * 0.998)];
        if (high <= low) high = low + 1;

        BufferedImage image = new BufferedImage(width, height, BufferedImage.TYPE_BYTE_GRAY);
        byte[] grayData = ((DataBufferByte) image.getRaster().getDataBuffer()).getData();
        double range = high - low;
        for (int i = 0; i < pixelCount; i++) {
            int stretched = (int) ((values[i] - low) * 255.0 / range);
            grayData[i] = (byte) Math.min(255, Math.max(0, stretched));
        }

        Path previewPath = storageDir.resolve("latest-preview.jpg");
        var writer = ImageIO.getImageWritersByFormatName("jpg").next();
        var param = writer.getDefaultWriteParam();
        param.setCompressionMode(ImageWriteParam.MODE_EXPLICIT);
        param.setCompressionQuality(0.85f);
        try (var fos = new FileOutputStream(previewPath.toFile());
             var out = new MemoryCacheImageOutputStream(fos)) {
            writer.setOutput(out);
            writer.write(null, new IIOImage(image, null, null), param);
        } finally {
            writer.dispose();
        }
    }
}
