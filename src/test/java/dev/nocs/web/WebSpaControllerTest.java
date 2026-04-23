package dev.nocs.web;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.forwardedUrl;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(
        properties = {
            "nocs.auth.token=test-token",
            "nocs.indi.mode=disabled",
        })
class WebSpaControllerTest {

    @Autowired
    MockMvc mvc;

    @Test
    void spaRouteForwardsToIndex() throws Exception {
        mvc.perform(get("/sequences/42").header("Authorization", "Bearer test-token"))
                .andExpect(forwardedUrl("/index.html"));
    }

    @Test
    void rootServesIndexHtml() throws Exception {
        mvc.perform(get("/index.html"))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith("text/html"));
    }

    @Test
    void apiStillRequiresAuth() throws Exception {
        mvc.perform(get("/api/config")).andExpect(status().isUnauthorized());
    }
}
