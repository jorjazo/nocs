package dev.nocs.target;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@TestPropertySource(properties = "nocs.auth.token=t")
class IntegrationTargetsApiTest {

    @Autowired JdbcTemplate jdbc;
    @LocalServerPort int port;
    final HttpClient http = HttpClient.newHttpClient();
    final ObjectMapper json = new ObjectMapper();

    @BeforeEach
    void seed() {
        jdbc.update("DELETE FROM observatories");
        jdbc.update("INSERT INTO observatories(name, latitude_deg, longitude_deg, elevation_m, timezone, is_active) "
                + "VALUES('IntTest', 40.0, -74.0, 10, 'UTC', 1)");
    }

    @Test
    void curlSearchM31() throws Exception {
        HttpResponse<String> resp = http.send(
                HttpRequest.newBuilder(URI.create("http://localhost:" + port + "/api/targets/search?q=M31"))
                        .header("Authorization", "Bearer t")
                        .GET()
                        .build(),
                HttpResponse.BodyHandlers.ofString());
        assertThat(resp.statusCode()).isEqualTo(200);
        JsonNode body = json.readTree(resp.body());
        assertThat(body.isArray()).isTrue();
        assertThat(body.get(0).get("target").get("id").asText()).isEqualTo("messier:M31");
        assertThat(body.get(0).get("observation").get("altitudeDeg").isNumber()).isTrue();
    }

    @Test
    void curlPlanetJupiter() throws Exception {
        HttpResponse<String> resp = http.send(
                HttpRequest.newBuilder(URI.create("http://localhost:" + port + "/api/targets/planet:jupiter"))
                        .header("Authorization", "Bearer t")
                        .GET()
                        .build(),
                HttpResponse.BodyHandlers.ofString());
        assertThat(resp.statusCode()).isEqualTo(200);
        JsonNode body = json.readTree(resp.body());
        assertThat(body.get("target").get("id").asText()).isEqualTo("planet:jupiter");
    }

    @Test
    void unauthenticatedIs401() throws Exception {
        HttpResponse<String> resp = http.send(
                HttpRequest.newBuilder(URI.create("http://localhost:" + port + "/api/targets/search?q=M31"))
                        .GET()
                        .build(),
                HttpResponse.BodyHandlers.ofString());
        assertThat(resp.statusCode()).isEqualTo(401);
    }
}
