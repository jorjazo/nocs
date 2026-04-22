package dev.nocs.config;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(properties = "nocs.auth.token=t")
class ConfigControllerTest {

    @Autowired
    MockMvc mvc;

    @Test
    void getEmptyConfigReturnsEmptyObject() throws Exception {
        mvc.perform(get("/api/config").header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$").isMap());
    }

    @Test
    void patchThenGetRoundTripsValues() throws Exception {
        mvc.perform(patch("/api/config")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"observatory.name\":\"Backyard\",\"observatory.elevation_m\":\"152\"}"))
                .andExpect(status().isOk());

        mvc.perform(get("/api/config").header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$['observatory.name']").value("Backyard"))
                .andExpect(jsonPath("$['observatory.elevation_m']").value("152"));
    }
}
