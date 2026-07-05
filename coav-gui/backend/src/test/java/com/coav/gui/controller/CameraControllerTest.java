package com.coav.gui.controller;

import com.coav.gui.model.CameraVerification;
import com.coav.gui.service.CameraStore;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(CameraController.class)
class CameraControllerTest {

    @Autowired
    MockMvc mvc;

    @MockBean
    CameraStore cameraStore;

    // --- GET /api/cameras — static network definition ---

    @Test
    void getCameras_returnsFourCamerasWithSpecCoordinatesAndCutoff() throws Exception {
        mvc.perform(get("/api/cameras"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.length()").value(4))
            .andExpect(jsonPath("$[0].id").value("CAM-ALPHA"))
            .andExpect(jsonPath("$[0].lat").value(50.60))
            .andExpect(jsonPath("$[0].lon").value(4.60))
            .andExpect(jsonPath("$[0].elevationCutoffDeg").value(20.0))
            .andExpect(jsonPath("$[1].id").value("CAM-BRAVO"))
            .andExpect(jsonPath("$[1].lat").value(51.90))
            .andExpect(jsonPath("$[1].lon").value(7.00))
            .andExpect(jsonPath("$[2].id").value("CAM-EHBK"))
            .andExpect(jsonPath("$[2].lat").value(50.92))
            .andExpect(jsonPath("$[2].lon").value(5.77))
            .andExpect(jsonPath("$[3].id").value("CAM-NORTH"))
            .andExpect(jsonPath("$[3].lat").value(52.30))
            .andExpect(jsonPath("$[3].lon").value(6.50));
    }

    // --- GET /api/camera-verification — TTL-filtered store view ---

    @Test
    void getCameraVerification_returnsStoreState() throws Exception {
        CameraVerification v = CameraVerification.builder()
            .cameraId("CAM-EHBK")
            .timestamp("2026-07-05T00:00:00Z")
            .contrailDetected(true)
            .confidence(0.87)
            .contrailPixelRatio(0.042)
            .contrailCount(3)
            .newContrailCount(1)
            .frameRef("gvccs_val_00734")
            .maskPngB64("iVBORw0KGgo=")
            .build();
        when(cameraStore.getVerifications()).thenReturn(List.of(v));

        mvc.perform(get("/api/camera-verification"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.length()").value(1))
            .andExpect(jsonPath("$[0].cameraId").value("CAM-EHBK"))
            .andExpect(jsonPath("$[0].contrailDetected").value(true))
            .andExpect(jsonPath("$[0].confidence").value(0.87))
            .andExpect(jsonPath("$[0].contrailCount").value(3))
            .andExpect(jsonPath("$[0].newContrailCount").value(1))
            .andExpect(jsonPath("$[0].frameRef").value("gvccs_val_00734"))
            // camera-keyed contract: no flight attribution field (P2)
            .andExpect(jsonPath("$[0].flightId").doesNotExist());
    }

    @Test
    void getCameraVerification_ttlExpired_returnsEmptyArray() throws Exception {
        // CameraStore.getVerifications() already applies the 5-min TTL —
        // the controller must pass the filtered (possibly empty) view through
        when(cameraStore.getVerifications()).thenReturn(List.of());

        mvc.perform(get("/api/camera-verification"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$").isArray())
            .andExpect(jsonPath("$").isEmpty());
    }
}
