package dev.nocs.target;

import dev.nocs.astronomy.Angles;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public final class SimbadResolver {

    /** SIMBAD ASCII: coords then a space and parenthesis, e.g. {@code ... 09.067 (Opt )}. */
    private static final Pattern COORD_LINE =
            Pattern.compile("Coordinates\\(ICRS[^)]+\\):\\s*([0-9:.+\\- ]+?)\\s*\\(");

    private final boolean enabled;
    private final String baseUrl;
    private final HttpClient client;

    public SimbadResolver(boolean enabled, String baseUrl) {
        this.enabled = enabled;
        this.baseUrl = baseUrl == null ? "https://simbad.u-strasbg.fr/simbad" : baseUrl;
        this.client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
    }

    public Optional<Target> resolve(String query) {
        if (!enabled || query == null || query.isBlank()) return Optional.empty();
        try {
            URI uri = URI.create(baseUrl
                    + "/sim-id?output.format=ASCII&Ident="
                    + URLEncoder.encode(query, StandardCharsets.UTF_8));
            HttpResponse<String> resp = client.send(
                    HttpRequest.newBuilder(uri).timeout(Duration.ofSeconds(8)).GET().build(),
                    HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (resp.statusCode() != 200) return Optional.empty();
            return parse(query, resp.body());
        } catch (Exception e) {
            return Optional.empty();
        }
    }

    static Optional<Target> parse(String query, String body) {
        Matcher m = COORD_LINE.matcher(body);
        if (!m.find()) return Optional.empty();
        String coords = m.group(1).trim();
        int splitIdx = findCoordSplit(coords);
        if (splitIdx < 0) return Optional.empty();
        String raStr = coords.substring(0, splitIdx).trim();
        String decStr = coords.substring(splitIdx).trim();
        try {
            double ra = Angles.parseHmsToDeg(raStr);
            double dec = Angles.parseDmsToDeg(decStr);
            return Optional.of(new Target(
                    "simbad:" + query,
                    query,
                    List.of(query),
                    TargetKind.OTHER,
                    ra,
                    dec,
                    "",
                    Double.NaN,
                    Double.NaN,
                    "resolved via SIMBAD"));
        } catch (Exception e) {
            return Optional.empty();
        }
    }

    private static int findCoordSplit(String coords) {
        // The first signed token (+/−) after at least one digit marks the declination.
        boolean sawDigit = false;
        for (int i = 0; i < coords.length(); i++) {
            char c = coords.charAt(i);
            if (Character.isDigit(c)) sawDigit = true;
            if (sawDigit && (c == '+' || c == '-') && i > 0 && coords.charAt(i - 1) == ' ') {
                return i;
            }
        }
        return -1;
    }
}
