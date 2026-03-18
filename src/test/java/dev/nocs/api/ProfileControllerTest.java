package dev.nocs.api;

import dev.nocs.domain.Profile;
import dev.nocs.service.ProfileService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;
import java.util.Optional;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(ProfileController.class)
class ProfileControllerTest {

    @Autowired
    MockMvc mockMvc;

    @MockBean
    ProfileService profileService;

    @Test
    void listProfiles() throws Exception {
        Profile p = new Profile("id1", "Profile 1", List.of());
        when(profileService.findAll()).thenReturn(List.of(p));

        mockMvc.perform(get("/profiles"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$").isArray())
                .andExpect(jsonPath("$[0].id").value("id1"))
                .andExpect(jsonPath("$[0].name").value("Profile 1"));
    }

    @Test
    void getLoadedProfile_empty() throws Exception {
        when(profileService.getLoadedProfileId()).thenReturn(Optional.empty());

        mockMvc.perform(get("/profiles/loaded"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").doesNotExist());
    }

    @Test
    void getLoadedProfile_returnsId() throws Exception {
        when(profileService.getLoadedProfileId()).thenReturn(Optional.of("id1"));

        mockMvc.perform(get("/profiles/loaded"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value("id1"));
    }

    @Test
    void getProfile() throws Exception {
        Profile p = new Profile("id1", "Profile 1", List.of("driver.one"));
        when(profileService.findById("id1")).thenReturn(Optional.of(p));

        mockMvc.perform(get("/profiles/id1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value("id1"))
                .andExpect(jsonPath("$.name").value("Profile 1"))
                .andExpect(jsonPath("$.driverIds").isArray());
    }

    @Test
    void getProfile_notFound() throws Exception {
        when(profileService.findById("nonexistent")).thenReturn(Optional.empty());

        mockMvc.perform(get("/profiles/nonexistent"))
                .andExpect(status().isNotFound());
    }

    @Test
    void createProfile() throws Exception {
        Profile created = new Profile("new-id", "New Profile", List.of("driver.one"));
        when(profileService.create("New Profile", List.of("driver.one"))).thenReturn(created);

        mockMvc.perform(post("/profiles")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"New Profile\",\"driverIds\":[\"driver.one\"]}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value("new-id"))
                .andExpect(jsonPath("$.name").value("New Profile"));
    }

    @Test
    void loadProfile() throws Exception {
        Profile p = new Profile("id1", "Profile 1", List.of());
        when(profileService.findById("id1")).thenReturn(Optional.of(p));

        mockMvc.perform(post("/profiles/id1/load"))
                .andExpect(status().isNoContent());

        verify(profileService).loadProfile("id1");
    }

    @Test
    void loadProfile_notFound() throws Exception {
        when(profileService.findById("nonexistent")).thenReturn(Optional.empty());

        mockMvc.perform(post("/profiles/nonexistent/load"))
                .andExpect(status().isNotFound());

        verify(profileService, never()).loadProfile(any());
    }

    @Test
    void unloadProfile() throws Exception {
        mockMvc.perform(post("/profiles/unload"))
                .andExpect(status().isNoContent());

        verify(profileService).unloadProfile();
    }
}
