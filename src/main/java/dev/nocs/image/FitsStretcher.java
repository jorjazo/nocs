package dev.nocs.image;

import java.awt.image.BufferedImage;
import java.nio.ByteBuffer;
import java.util.Arrays;

public final class FitsStretcher {

    private FitsStretcher() {}

    /** Reads pixels per BITPIX, applies BZERO/BSCALE, MAD-percentile stretches, downsamples to maxDim. */
    public static BufferedImage stretch(FitsHeaderReader.Header h, byte[] fits, int maxDim) {
        if (h.naxis() != 2) {
            throw new IllegalArgumentException("only NAXIS=2 supported, got " + h.naxis());
        }
        if (h.bitpix() != 16 && h.bitpix() != -32) {
            throw new IllegalArgumentException("only BITPIX in {16,-32} supported, got " + h.bitpix());
        }
        int w = h.naxis1();
        int h2 = h.naxis2();
        if (w <= 0 || h2 <= 0) {
            throw new IllegalArgumentException("invalid dimensions: " + w + "x" + h2);
        }
        float[] phys = readPhysical(h, fits, w * h2);
        float[] stats = madPercentiles(phys);
        float lo = stats[0];
        float hi = stats[1];
        float pMin = phys[0];
        float pMax = phys[0];
        for (float v : phys) {
            if (v < pMin) pMin = v;
            if (v > pMax) pMax = v;
        }
        float spanData = pMax - pMin;
        float spanWindow = hi - lo;
        if (spanData > 0 && spanWindow > spanData * 5f) {
            lo = pMin;
            hi = pMax;
        }
        if (hi <= lo) {
            hi = lo + 1f;
        }

        BufferedImage full = new BufferedImage(w, h2, BufferedImage.TYPE_BYTE_GRAY);
        var wr = full.getRaster();
        for (int y = 0; y < h2; y++) {
            for (int x = 0; x < w; x++) {
                float v = phys[y * w + x];
                int g = clamp((int) (((v - lo) / (hi - lo)) * 255f));
                wr.setSample(x, y, 0, g);
            }
        }
        return downscale(full, maxDim);
    }

    private static float[] readPhysical(FitsHeaderReader.Header h, byte[] fits, int n) {
        ByteBuffer body = ByteBuffer.wrap(fits, h.dataOffset(), fits.length - h.dataOffset());
        float[] out = new float[n];
        if (h.bitpix() == 16) {
            for (int i = 0; i < n; i++) {
                short raw = body.getShort();
                out[i] = (float) (raw * h.bscale() + h.bzero());
            }
        } else {
            for (int i = 0; i < n; i++) {
                out[i] = (float) (body.getFloat() * h.bscale() + h.bzero());
            }
        }
        return out;
    }

    static float[] madPercentiles(float[] pixels) {
        if (pixels.length == 0) {
            return new float[]{0f, 1f};
        }
        int sampleSize = Math.min(pixels.length, 20_000);
        float[] sample = new float[sampleSize];
        if (sampleSize == pixels.length) {
            System.arraycopy(pixels, 0, sample, 0, sampleSize);
        } else {
            int stride = pixels.length / sampleSize;
            for (int i = 0; i < sampleSize; i++) {
                sample[i] = pixels[i * stride];
            }
        }
        Arrays.sort(sample);
        float median = sample[sample.length / 2];
        float[] dev = new float[sample.length];
        for (int i = 0; i < sample.length; i++) {
            dev[i] = Math.abs(sample[i] - median);
        }
        Arrays.sort(dev);
        float mad = dev[dev.length / 2];
        float sigma = 1.4826f * mad;
        float lo;
        float hi;
        if (mad == 0f || Float.isNaN(sigma)) {
            lo = sample[0];
            hi = sample[sample.length - 1];
        } else {
            lo = median - 3f * sigma;
            hi = median + 3f * sigma;
        }
        if (hi <= lo) {
            hi = lo + 1f;
        }
        return new float[]{lo, hi};
    }

    private static int clamp(int v) {
        if (v < 0) return 0;
        if (v > 255) return 255;
        return v;
    }

    private static BufferedImage downscale(BufferedImage src, int maxDim) {
        int w = src.getWidth();
        int h = src.getHeight();
        if (w <= maxDim && h <= maxDim) {
            return src;
        }
        double scale = (double) maxDim / Math.max(w, h);
        int nw = Math.max(1, (int) Math.round(w * scale));
        int nh = Math.max(1, (int) Math.round(h * scale));
        BufferedImage out = new BufferedImage(nw, nh, BufferedImage.TYPE_BYTE_GRAY);
        var outR = out.getRaster();
        for (int y = 0; y < nh; y++) {
            int sy = Math.min(h - 1, (int) (y / scale));
            for (int x = 0; x < nw; x++) {
                int sx = Math.min(w - 1, (int) (x / scale));
                int g = src.getRaster().getSample(sx, sy, 0);
                outR.setSample(x, y, 0, g);
            }
        }
        return out;
    }
}
