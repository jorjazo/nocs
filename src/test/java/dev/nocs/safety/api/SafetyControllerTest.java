package dev.nocs.safety.api;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(properties = "nocs.auth.token=t")
class SafetyControllerTest {

    @Autowired
    MockMvc mvc;

    @Test
    void rulesEndpointReturnsArray() throws Exception {
        mvc.perform(get("/api/safety/rules").header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.rules").isArray())
                .andExpect(jsonPath("$.latched").isArray());
    }

    @Test
    void eStopAcceptsEmptyBody() throws Exception {
        mvc.perform(post("/api/safety/e-stop")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isOk());
    }

    @Test
    void resetAcceptsNoBody() throws Exception {
        mvc.perform(post("/api/safety/reset").header("Authorization", "Bearer t"))
                .andExpect(status().isOk());
    }

    @Test
    void sensorReadingValidatesRequiredFields() throws Exception {
        mvc.perform(post("/api/safety/sensors/readings")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"sensor\":\"weather\",\"values\":{\"humidity\":80}}"))
                .andExpect(status().isOk());

        mvc.perform(post("/api/safety/sensors/readings")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"values\":{}}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void activeTargetEndpoint() throws Exception {
        mvc.perform(post("/api/safety/active-target")
                        .header("Authorization", "Bearer t")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"targetId\":\"messier:M31\",\"raJ2000Deg\":10.685,\"decJ2000Deg\":41.269}"))
                .andExpect(status().isOk());
    }

    @Test
    void reloadEndpoint() throws Exception {
        mvc.perform(post("/api/safety/rules/reload").header("Authorization", "Bearer t"))
                .andExpect(status().isOk());
    }

    @Test
    void rulesEndpointRequiresAuth() throws Exception {
        mvc.perform(get("/api/safety/rules")).andExpect(status().isUnauthorized());
    }
}
