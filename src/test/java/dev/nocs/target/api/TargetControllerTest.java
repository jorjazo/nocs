package dev.nocs.target.api;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(properties = "nocs.auth.token=t")
class TargetControllerTest {

    @Autowired MockMvc mvc;
    @Autowired JdbcTemplate jdbc;

    @BeforeEach
    void reset() {
        jdbc.update("DELETE FROM observatories");
        jdbc.update("DELETE FROM targets_custom");
        jdbc.update("INSERT INTO observatories(name, latitude_deg, longitude_deg, elevation_m, timezone, is_active) "
                + "VALUES('t', 40.0, -74.0, 0, 'UTC', 1)");
    }

    @Test
    void searchM31ReturnsObservation() throws Exception {
        mvc.perform(get("/api/targets/search").param("q", "M31").header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].target.id").value("messier:M31"))
                .andExpect(jsonPath("$[0].observation.altitudeDeg").isNumber())
                .andExpect(jsonPath("$[0].observation.azimuthDeg").isNumber())
                .andExpect(jsonPath("$[0].observation.transitUtc").exists());
    }

    @Test
    void getByIdReturnsM31() throws Exception {
        mvc.perform(get("/api/targets/messier:M31").header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.target.primaryName").value("M31"));
    }

    @Test
    void getByIdUnknownReturns404() throws Exception {
        mvc.perform(get("/api/targets/messier:M999").header("Authorization", "Bearer t"))
                .andExpect(status().isNotFound());
    }

    @Test
    void customTargetRoundTrip() throws Exception {
        String body = mvc.perform(post("/api/targets/custom")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(
                                """
                                { "name":"Dark Nebula X","raJ2000Deg":200.0,"decJ2000Deg":-30.0,"notes":"test" }"""))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").isNumber())
                .andReturn().getResponse().getContentAsString();
        long id = Long.parseLong(body.replaceAll(".*\"id\"\\s*:\\s*(\\d+).*", "$1"));

        mvc.perform(get("/api/targets/custom:" + id).header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.target.primaryName").value("Dark Nebula X"));

        mvc.perform(delete("/api/targets/custom/" + id).header("Authorization", "Bearer t"))
                .andExpect(status().isOk());

        mvc.perform(get("/api/targets/custom:" + id).header("Authorization", "Bearer t"))
                .andExpect(status().isNotFound());
    }

    @Test
    void missingObservatoryLeavesObservationEmpty() throws Exception {
        jdbc.update("DELETE FROM observatories");
        mvc.perform(get("/api/targets/messier:M31").header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.observation").doesNotExist());
    }
}
