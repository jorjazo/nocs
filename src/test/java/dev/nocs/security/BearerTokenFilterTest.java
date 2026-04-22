package dev.nocs.security;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(properties = "nocs.auth.token=test-token-abc")
class BearerTokenFilterTest {

    @Autowired
    MockMvc mockMvc;

    @Test
    void apiRequestsRequireToken() throws Exception {
        mockMvc.perform(get("/api/config"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void apiRequestsAcceptValidToken() throws Exception {
        mockMvc.perform(get("/api/config").header("Authorization", "Bearer test-token-abc"))
                .andExpect(status().isNotFound());
    }

    @Test
    void staticAssetsAreOpen() throws Exception {
        mockMvc.perform(get("/"))
                .andExpect(status().isOk());
    }

    @Test
    void wrongTokenIsRejected() throws Exception {
        mockMvc.perform(get("/api/config").header("Authorization", "Bearer wrong"))
                .andExpect(status().isUnauthorized());
    }
}
