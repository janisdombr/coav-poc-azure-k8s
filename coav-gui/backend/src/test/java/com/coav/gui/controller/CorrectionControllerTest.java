package com.coav.gui.controller;

import com.coav.gui.model.Correction;
import com.coav.gui.model.Flight;
import com.coav.gui.service.CorrectionRateLimiter;
import com.coav.gui.service.FlightStateStore;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.test.web.servlet.MockMvc;

import org.junit.jupiter.api.BeforeEach;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(CorrectionController.class)
class CorrectionControllerTest {

    @Autowired
    MockMvc mvc;

    @Autowired
    ObjectMapper objectMapper;

    @MockBean
    SimpMessagingTemplate messagingTemplate;

    @MockBean
    CorrectionRateLimiter rateLimiter;

    @MockBean
    FlightStateStore flightStateStore;

    @BeforeEach
    void allowRateLimit() {
        when(rateLimiter.allow(anyString())).thenReturn(true);
    }

    @Test
    void postCorrection_rateLimitExceeded_returns429() throws Exception {
        when(rateLimiter.allow(anyString())).thenReturn(false);
        mvc.perform(post("/api/correction")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"flightId\":\"C100-CLB\",\"newAltitudeFt\":35000}"))
            .andExpect(status().isTooManyRequests());
    }

    @Test
    void postCorrection_validPayload_returnsAccepted() throws Exception {
        when(flightStateStore.getAllFlights()).thenReturn(java.util.List.of(
            Flight.builder().flightId("C100-CLB").altitudeFt(35000).build()));

        Correction c = new Correction();
        c.setFlightId("C100-CLB");
        c.setNewAltitudeFt(37000);
        c.setReason("Contrail avoidance - route FL370");

        mvc.perform(post("/api/correction")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(c)))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.status").value("ACCEPTED"))
            .andExpect(jsonPath("$.flightId").value("C100-CLB"))
            .andExpect(jsonPath("$.message").value(
                "ATCO correction logged: C100-CLB FL350 → FL370 — advisory support only, not a clearance"))
            .andExpect(jsonPath("$.timestamp").isNotEmpty());
    }

    @Test
    void postCorrection_lowercaseFlightId_returns400() throws Exception {
        // OWASP A03 — pattern ^[A-Z0-9\-]+$ must reject lowercase
        mvc.perform(post("/api/correction")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"flightId\":\"abc-123\",\"newAltitudeFt\":35000}"))
            .andExpect(status().isBadRequest());
    }

    @Test
    void postCorrection_flightIdWithSpaces_returns400() throws Exception {
        mvc.perform(post("/api/correction")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"flightId\":\"C100 CLB\",\"newAltitudeFt\":35000}"))
            .andExpect(status().isBadRequest());
    }

    @Test
    void postCorrection_missingFlightId_returns400() throws Exception {
        mvc.perform(post("/api/correction")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"newAltitudeFt\":35000}"))
            .andExpect(status().isBadRequest());
    }

    @Test
    void postCorrection_altitudeTooHigh_returns400() throws Exception {
        // Max altitude enforced: 60000 ft
        mvc.perform(post("/api/correction")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"flightId\":\"C100-CLB\",\"newAltitudeFt\":99999}"))
            .andExpect(status().isBadRequest());
    }

    @Test
    void postCorrection_negativeAltitude_returns400() throws Exception {
        mvc.perform(post("/api/correction")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"flightId\":\"C100-CLB\",\"newAltitudeFt\":-1000}"))
            .andExpect(status().isBadRequest());
    }

    @Test
    void postCorrection_emptyBody_returns400() throws Exception {
        mvc.perform(post("/api/correction")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{}"))
            .andExpect(status().isBadRequest());
    }
}
