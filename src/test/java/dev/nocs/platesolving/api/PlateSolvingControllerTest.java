package dev.nocs.platesolving.api;

import dev.nocs.image.ImageStoreService;
import dev.nocs.platesolving.FailureKind;
import dev.nocs.platesolving.PlateSolution;
import dev.nocs.platesolving.PlateSolvingService;
import dev.nocs.platesolving.SolveOptions;
import dev.nocs.platesolving.SolveOutcome;
import dev.nocs.platesolving.install.AstapInstallService;
import dev.nocs.platesolving.install.InstallProgress;
import java.time.Instant;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(properties = "nocs.auth.token=t")
class PlateSolvingControllerTest {

    @Autowired MockMvc mvc;

    @MockBean PlateSolvingService solver;
    @MockBean ImageStoreService imageStore;
    @MockBean AstapInstallService installService;

    @Test
    void solveRequiresImageId() throws Exception {
        mvc.perform(post("/api/platesolving/solve")
                        .header("Authorization", "Bearer t")
                        .contentType("application/json")
                        .content("{}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void solveSuccessReturnsSolution() throws Exception {
        when(imageStore.loadFits(anyLong())).thenReturn(Optional.of(new byte[16]));
        PlateSolution sol = new PlateSolution(
                10.6847083, 41.269083, 1.234, 12.5, 0.5, 0.4, Instant.now(), "astap");
        when(solver.solve(any(), any(SolveOptions.class)))
                .thenReturn(new SolveOutcome.Solved(sol, 1234L));
        when(imageStore.amendHeader(anyLong(), any())).thenReturn(true);

        mvc.perform(post("/api/platesolving/solve")
                        .header("Authorization", "Bearer t")
                        .contentType("application/json")
                        .content("{\"image_id\":42}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.solved").value(true))
                .andExpect(jsonPath("$.solution.ra_j2000_deg").value(10.6847083))
                .andExpect(jsonPath("$.solution.duration_ms").value(1234));
    }

    @Test
    void solveFailureReturns422() throws Exception {
        when(imageStore.loadFits(anyLong())).thenReturn(Optional.of(new byte[16]));
        when(solver.solve(any(), any(SolveOptions.class)))
                .thenReturn(new SolveOutcome.Failed(FailureKind.NO_STARS, "too few stars", 200L));

        mvc.perform(post("/api/platesolving/solve")
                        .header("Authorization", "Bearer t")
                        .contentType("application/json")
                        .content("{\"image_id\":42}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.solved").value(false))
                .andExpect(jsonPath("$.failure_kind").value("no_stars"));
    }

    @Test
    void installStatusReturnsJson() throws Exception {
        mvc.perform(get("/api/platesolving/install")
                        .header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.supported_platform").exists());
    }

    @Test
    void installStartRespectsLicenseFlag() throws Exception {
        doThrow(new IllegalArgumentException("must accept ASTAP license to install"))
                .when(installService).start(any());
        mvc.perform(post("/api/platesolving/install")
                        .header("Authorization", "Bearer t")
                        .contentType("application/json")
                        .content("{\"accept_license\": false}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void installProgressReturnsJson() throws Exception {
        when(installService.progress()).thenReturn(InstallProgress.idle());
        mvc.perform(get("/api/platesolving/install/progress")
                        .header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.phase").value("idle"));
    }

    @Test
    void unauthenticatedSolveIs401() throws Exception {
        mvc.perform(post("/api/platesolving/solve")
                        .contentType("application/json")
                        .content("{\"image_id\":42}"))
                .andExpect(status().isUnauthorized());
    }
}
