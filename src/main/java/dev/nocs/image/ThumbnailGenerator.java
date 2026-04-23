package dev.nocs.image;

import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.util.Iterator;
import java.util.Optional;
import javax.imageio.IIOImage;
import javax.imageio.ImageIO;
import javax.imageio.ImageWriteParam;
import javax.imageio.ImageWriter;
import javax.imageio.stream.ImageOutputStream;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

@Component
public class ThumbnailGenerator {

    private static final Logger log = LoggerFactory.getLogger(ThumbnailGenerator.class);
    private static final int MAX_DIM = 512;
    private static final float JPEG_QUALITY = 0.85f;

    public Optional<byte[]> generate(byte[] fitsBytes) {
        FitsHeaderReader.Header h;
        try {
            h = FitsHeaderReader.read(fitsBytes);
        } catch (IllegalArgumentException e) {
            log.warn("thumbnail: failed to parse FITS header ({})", e.getMessage());
            return Optional.empty();
        }
        if (h.naxis() != 2 || (h.bitpix() != 16 && h.bitpix() != -32)) {
            log.info("thumbnail: skipping unsupported FITS variant (bitpix={}, naxis={})",
                    h.bitpix(), h.naxis());
            return Optional.empty();
        }
        try {
            BufferedImage img = FitsStretcher.stretch(h, fitsBytes, MAX_DIM);
            return Optional.of(encodeJpeg(img));
        } catch (Exception e) {
            log.warn("thumbnail: failed to stretch/encode ({})", e.getMessage());
            return Optional.empty();
        }
    }

    private static byte[] encodeJpeg(BufferedImage img) throws IOException {
        BufferedImage rgb = toRgb(img);
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        Iterator<ImageWriter> writers = ImageIO.getImageWritersByFormatName("jpg");
        if (!writers.hasNext()) {
            throw new IOException("no JPEG writer available");
        }
        ImageWriter writer = writers.next();
        try (ImageOutputStream ios = ImageIO.createImageOutputStream(out)) {
            writer.setOutput(ios);
            ImageWriteParam param = writer.getDefaultWriteParam();
            param.setCompressionMode(ImageWriteParam.MODE_EXPLICIT);
            param.setCompressionQuality(JPEG_QUALITY);
            writer.write(null, new IIOImage(rgb, null, null), param);
        } finally {
            writer.dispose();
        }
        return out.toByteArray();
    }

    private static BufferedImage toRgb(BufferedImage img) {
        if (img.getType() == BufferedImage.TYPE_INT_RGB || img.getType() == BufferedImage.TYPE_3BYTE_BGR) {
            return img;
        }
        BufferedImage rgb = new BufferedImage(img.getWidth(), img.getHeight(), BufferedImage.TYPE_INT_RGB);
        var in = img.getRaster();
        for (int y = 0; y < img.getHeight(); y++) {
            for (int x = 0; x < img.getWidth(); x++) {
                int g = in.getSample(x, y, 0);
                rgb.setRGB(x, y, (g << 16) | (g << 8) | g);
            }
        }
        return rgb;
    }
}
