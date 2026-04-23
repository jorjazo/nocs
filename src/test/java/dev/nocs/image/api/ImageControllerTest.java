package dev.nocs.image.api;

import dev.nocs.device.DeviceId;
import dev.nocs.image.CaptureContext;
import dev.nocs.image.ImageStoreService;
import dev.nocs.image.MiniFits;
import java.time.Duration;
import java.util.Map;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(properties = "nocs.auth.token=t")
class ImageControllerTest {

    @Autowired
    MockMvc mvc;
    @Autowired
    ImageStoreService store;

    @Test
    void listGetFitsThumbAndDelete() throws Exception {
        DeviceId cam = new DeviceId("ccd-rest");
        store.prepareCapture(cam, new CaptureContext("R", "M42", 30.0, "R_30s", 1));
        byte[] fits = MiniFits.build16(8, 8, new short[64], Map.of(
                "DATE-OBS", "'2026-04-22T22:30:00'"));
        store.accept(cam, fits, ".fits");

        Awaitility.await().atMost(Duration.ofSeconds(3))
                .until(() -> !store.list(new dev.nocs.image.ImageRepository.Filters(
                        cam.value(), null, null, null, 10, 0)).isEmpty());

        long id = store.list(new dev.nocs.image.ImageRepository.Filters(
                cam.value(), null, null, null, 10, 0)).get(0).id();

        mvc.perform(get("/api/images?device=ccd-rest").header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$").isArray())
                .andExpect(jsonPath("$[0].id").value((int) id));

        mvc.perform(get("/api/images/" + id).header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.filter").value("R"))
                .andExpect(jsonPath("$.target").value("M42"));

        MvcResult fitsResult = mvc.perform(get("/api/images/" + id + ".fits")
                        .header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(header().string("Content-Type", "application/fits"))
                .andReturn();
        assertThat(fitsResult.getResponse().getContentAsByteArray()).isEqualTo(fits);

        mvc.perform(get("/api/images/" + id + "/thumb.jpg")
                        .header("Authorization", "Bearer t"))
                .andExpect(status().isOk())
                .andExpect(header().string("Content-Type", "image/jpeg"));

        mvc.perform(delete("/api/images/" + id).header("Authorization", "Bearer t"))
                .andExpect(status().isNoContent());
        mvc.perform(get("/api/images/" + id).header("Authorization", "Bearer t"))
                .andExpect(status().isNotFound());
    }

    @Test
    void unauthorizedRejected() throws Exception {
        mvc.perform(get("/api/images")).andExpect(status().isUnauthorized());
    }

    @Test
    void unknownIdReturns404() throws Exception {
        mvc.perform(get("/api/images/99999999").header("Authorization", "Bearer t"))
                .andExpect(status().isNotFound());
        mvc.perform(get("/api/images/99999999.fits").header("Authorization", "Bearer t"))
                .andExpect(status().isNotFound());
    }

    @Test
    void thumbAbsentWhenSkipped() throws Exception {
        DeviceId cam = new DeviceId("ccd-nothumb");
        byte[] block = new byte[2880];
        java.util.Arrays.fill(block, (byte) ' ');
        write(block, 0, "SIMPLE  =                    T");
        write(block, 80, "BITPIX  =                    8");
        write(block, 160, "NAXIS   =                    2");
        write(block, 240, "NAXIS1  =                    4");
        write(block, 320, "NAXIS2  =                    4");
        write(block, 400, "END");
        store.accept(cam, block, ".fits");

        Awaitility.await().atMost(Duration.ofSeconds(2))
                .until(() -> !store.list(new dev.nocs.image.ImageRepository.Filters(
                        cam.value(), null, null, null, 10, 0)).isEmpty());
        long id = store.list(new dev.nocs.image.ImageRepository.Filters(
                cam.value(), null, null, null, 10, 0)).get(0).id();

        mvc.perform(get("/api/images/" + id + "/thumb.jpg")
                        .header("Authorization", "Bearer t"))
                .andExpect(status().isNotFound());

        mvc.perform(delete("/api/images/" + id).header("Authorization", "Bearer t"))
                .andExpect(status().isNoContent());
    }

    private static void write(byte[] target, int offset, String s) {
        byte[] bytes = s.getBytes();
        System.arraycopy(bytes, 0, target, offset, Math.min(bytes.length, 80));
    }
}
