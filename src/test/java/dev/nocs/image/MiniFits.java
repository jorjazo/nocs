package dev.nocs.image;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.util.LinkedHashMap;
import java.util.Map;

/** Builds a tiny FITS file (primary HDU, BITPIX=16 or BITPIX=-32) for tests. */
public final class MiniFits {

    private MiniFits() {}

    public static byte[] build16(int width, int height, short[] pixels, Map<String, String> extraCards) {
        if (pixels.length != width * height) {
            throw new IllegalArgumentException("pixel count != width*height");
        }
        Map<String, String> cards = baseCards(16, width, height);
        cards.put("BZERO", String.valueOf(32768));
        cards.put("BSCALE", String.valueOf(1));
        if (extraCards != null) {
            cards.putAll(extraCards);
        }
        byte[] header = encodeHeader(cards);
        ByteBuffer body = ByteBuffer.allocate(round2880(pixels.length * 2));
        for (short s : pixels) {
            body.putShort(s);
        }
        return concat(header, body.array());
    }

    public static byte[] buildFloat(int width, int height, float[] pixels, Map<String, String> extraCards) {
        if (pixels.length != width * height) {
            throw new IllegalArgumentException("pixel count != width*height");
        }
        Map<String, String> cards = baseCards(-32, width, height);
        if (extraCards != null) {
            cards.putAll(extraCards);
        }
        byte[] header = encodeHeader(cards);
        ByteBuffer body = ByteBuffer.allocate(round2880(pixels.length * 4));
        for (float f : pixels) {
            body.putFloat(f);
        }
        return concat(header, body.array());
    }

    private static Map<String, String> baseCards(int bitpix, int w, int h) {
        Map<String, String> cards = new LinkedHashMap<>();
        cards.put("SIMPLE", "T");
        cards.put("BITPIX", String.valueOf(bitpix));
        cards.put("NAXIS", "2");
        cards.put("NAXIS1", String.valueOf(w));
        cards.put("NAXIS2", String.valueOf(h));
        return cards;
    }

    private static byte[] encodeHeader(Map<String, String> cards) {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        try {
            for (var entry : cards.entrySet()) {
                out.write(card(entry.getKey(), entry.getValue()));
            }
            out.write(card("END", null));
        } catch (IOException ignored) {
            // ByteArrayOutputStream never throws.
        }
        int padding = round2880(out.size()) - out.size();
        for (int i = 0; i < padding; i++) {
            out.write(' ');
        }
        return out.toByteArray();
    }

    private static byte[] card(String key, String value) {
        StringBuilder sb = new StringBuilder(80);
        sb.append(String.format("%-8s", key));
        if (value == null) {
            for (int i = sb.length(); i < 80; i++) {
                sb.append(' ');
            }
            return sb.toString().getBytes();
        }
        sb.append("= ");
        String formatted;
        if (value.startsWith("'") || value.equals("T") || value.equals("F") || isNumeric(value)) {
            formatted = String.format("%20s", value);
        } else {
            formatted = String.format("'%-18s'", value);
        }
        sb.append(formatted);
        for (int i = sb.length(); i < 80; i++) {
            sb.append(' ');
        }
        return sb.substring(0, 80).getBytes();
    }

    private static boolean isNumeric(String s) {
        try {
            Double.parseDouble(s);
            return true;
        } catch (NumberFormatException e) {
            return false;
        }
    }

    private static int round2880(int n) {
        return ((n + 2879) / 2880) * 2880;
    }

    private static byte[] concat(byte[] a, byte[] b) {
        byte[] out = new byte[a.length + b.length];
        System.arraycopy(a, 0, out, 0, a.length);
        System.arraycopy(b, 0, out, a.length, b.length);
        return out;
    }
}
