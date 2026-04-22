package dev.nocs.observatory.api;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(properties = "nocs.auth.token=t")
class ObservatoryControllerTest {

    @Autowired MockMvc mvc;
    @Autowired JdbcTemplate jdbc;

    @BeforeEach
    void reset() {
        jdbc.update("DELETE FROM observatories");
    }

    @Test
    void createListActivateRoundTrip() throws Exception {
        mvc.perform(post("/api/observatories")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(
                                """
                                { "name":"Backyard",
                                  "latitudeDeg": 40.0,
                                  "longitudeDeg": -74.0,
                                  "elevationM": 50.0,
                                  "timezone": "America/New_York",
                                  "horizonMaskJson": "[]" }"""))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").isNumber())
                .andExpect(jsonPath("$.name").value("Backyard"))
                .andExpect(jsonPath("$.active").value(true));

        mvc.perform(get("/api/observatories").header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$").isArray())
                .andExpect(jsonPath("$[0].name").value("Backyard"));
    }

    @Test
    void unauthenticatedRejected() throws Exception {
        mvc.perform(get("/api/observatories")).andExpect(status().isUnauthorized());
    }

    @Test
    void rejectsInvalidHorizonMask() throws Exception {
        mvc.perform(post("/api/observatories")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(
                                """
                                { "name":"A","latitudeDeg":0,"longitudeDeg":0,"elevationM":0,
                                  "timezone":"UTC","horizonMaskJson":"not-json" }"""))
                .andExpect(status().isBadRequest());
    }
}
