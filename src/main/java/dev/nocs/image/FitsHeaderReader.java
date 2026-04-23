package dev.nocs.image;

import java.nio.charset.StandardCharsets;

public final class FitsHeaderReader {

    private FitsHeaderReader() {}

    public record Header(
            int bitpix,
            int naxis,
            int naxis1,
            int naxis2,
            double bzero,
            double bscale,
            String dateObs,
            int dataOffset) {}

    public static Header read(byte[] bytes) {
        if (bytes == null || bytes.length < 2880) {
            throw new IllegalArgumentException("FITS payload too small: " + (bytes == null ? 0 : bytes.length));
        }
        Integer bitpix = null;
        Integer naxis = null;
        Integer naxis1 = null;
        Integer naxis2 = null;
        double bzero = 0.0;
        double bscale = 1.0;
        String dateObs = null;

        int blocks = bytes.length / 2880;
        for (int b = 0; b < blocks; b++) {
            int blockOffset = b * 2880;
            for (int c = 0; c < 36; c++) {
                int cardOffset = blockOffset + c * 80;
                String card = new String(bytes, cardOffset, 80, StandardCharsets.US_ASCII);
                String key = card.substring(0, 8).trim();
                if ("END".equals(key)) {
                    int dataOffset = (b + 1) * 2880;
                    return finish(bitpix, naxis, naxis1, naxis2, bzero, bscale, dateObs, dataOffset);
                }
                if (card.length() < 10 || card.charAt(8) != '=') {
                    continue;
                }
                String rawValue = card.substring(10).trim();
                String value = stripQuotes(splitComment(rawValue));
                switch (key) {
                    case "BITPIX" -> bitpix = parseInt(value);
                    case "NAXIS" -> naxis = parseInt(value);
                    case "NAXIS1" -> naxis1 = parseInt(value);
                    case "NAXIS2" -> naxis2 = parseInt(value);
                    case "BZERO" -> bzero = parseDouble(value, 0.0);
                    case "BSCALE" -> bscale = parseDouble(value, 1.0);
                    case "DATE-OBS" -> dateObs = value;
                    default -> {
                        // ignore other cards
                    }
                }
            }
        }
        throw new IllegalArgumentException("FITS header missing END card");
    }

    private static Header finish(Integer bitpix, Integer naxis, Integer naxis1, Integer naxis2,
                                 double bzero, double bscale, String dateObs, int dataOffset) {
        if (bitpix == null) {
            throw new IllegalArgumentException("FITS header missing BITPIX");
        }
        if (naxis == null) {
            throw new IllegalArgumentException("FITS header missing NAXIS");
        }
        return new Header(
                bitpix, naxis,
                naxis1 == null ? 0 : naxis1,
                naxis2 == null ? 0 : naxis2,
                bzero, bscale, dateObs, dataOffset);
    }

    private static String splitComment(String value) {
        boolean inQuote = false;
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (c == '\'') {
                inQuote = !inQuote;
            } else if (c == '/' && !inQuote) {
                return value.substring(0, i).trim();
            }
        }
        return value.trim();
    }

    private static String stripQuotes(String s) {
        if (s.length() >= 2 && s.charAt(0) == '\'' && s.charAt(s.length() - 1) == '\'') {
            return s.substring(1, s.length() - 1).trim();
        }
        return s;
    }

    private static int parseInt(String s) {
        return Integer.parseInt(s.trim());
    }

    private static double parseDouble(String s, double fallback) {
        try {
            return Double.parseDouble(s.trim());
        } catch (NumberFormatException e) {
            return fallback;
        }
    }
}
