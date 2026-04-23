package dev.nocs.image;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.SequencedMap;

public final class FitsHeaderWriter {

    private static final int CARD_LEN = 80;
    private static final int BLOCK_LEN = 2880;

    private FitsHeaderWriter() {}

    public static byte[] writeWithCards(byte[] originalFits, SequencedMap<String, String> additions) {
        if (originalFits == null || originalFits.length < BLOCK_LEN) {
            throw new IllegalArgumentException("FITS payload too small");
        }
        FitsHeaderReader.Header h = FitsHeaderReader.read(originalFits);

        List<String> cards = readHeaderCards(originalFits, h.dataOffset());

        LinkedHashMap<String, String> overrides = new LinkedHashMap<>();
        if (additions != null) {
            additions.forEach((k, v) -> overrides.put(k.toUpperCase(Locale.ROOT), v));
        }

        List<String> rebuilt = new ArrayList<>(cards.size() + overrides.size());
        for (String card : cards) {
            String key = card.length() >= 8 ? card.substring(0, 8).trim() : "";
            if (key.equals("END")) {
                continue;
            }
            String upper = key.toUpperCase(Locale.ROOT);
            if (overrides.containsKey(upper)) {
                rebuilt.add(formatCard(upper, overrides.remove(upper)));
            } else {
                rebuilt.add(card);
            }
        }
        for (var entry : overrides.entrySet()) {
            rebuilt.add(formatCard(entry.getKey(), entry.getValue()));
        }
        rebuilt.add(formatCard("END", null));

        byte[] headerBytes = packHeader(rebuilt);
        int dataLen = originalFits.length - h.dataOffset();
        byte[] out = new byte[headerBytes.length + dataLen];
        System.arraycopy(headerBytes, 0, out, 0, headerBytes.length);
        System.arraycopy(originalFits, h.dataOffset(), out, headerBytes.length, dataLen);
        return out;
    }

    private static List<String> readHeaderCards(byte[] bytes, int dataOffset) {
        List<String> out = new ArrayList<>(dataOffset / CARD_LEN);
        for (int off = 0; off < dataOffset; off += CARD_LEN) {
            String card = new String(bytes, off, CARD_LEN, StandardCharsets.US_ASCII);
            String key = card.substring(0, 8).trim();
            out.add(card);
            if (key.equals("END")) {
                break;
            }
        }
        return out;
    }

    private static byte[] packHeader(List<String> cards) {
        int totalCards = ((cards.size() + 35) / 36) * 36;
        StringBuilder sb = new StringBuilder(totalCards * CARD_LEN);
        for (String c : cards) {
            sb.append(pad(c, CARD_LEN));
        }
        for (int i = cards.size(); i < totalCards; i++) {
            sb.append(pad("", CARD_LEN));
        }
        return sb.toString().getBytes(StandardCharsets.US_ASCII);
    }

    private static String formatCard(String key, String value) {
        String k = pad(key.toUpperCase(Locale.ROOT), 8);
        if ("END".equalsIgnoreCase(key)) {
            return pad("END", CARD_LEN);
        }
        String v = value == null ? "" : value;
        String formatted;
        if (v.length() >= 2 && v.startsWith("'") && v.endsWith("'")) {
            formatted = v;
        } else {
            formatted = String.format(Locale.ROOT, "%20s", v);
        }
        return pad(k + "= " + formatted, CARD_LEN);
    }

    private static String pad(String s, int len) {
        if (s.length() >= len) {
            return s.substring(0, len);
        }
        StringBuilder sb = new StringBuilder(len);
        sb.append(s);
        for (int i = s.length(); i < len; i++) {
            sb.append(' ');
        }
        return sb.toString();
    }
}
