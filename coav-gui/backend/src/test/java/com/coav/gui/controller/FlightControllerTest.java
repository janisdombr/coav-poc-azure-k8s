package com.coav.gui.controller;

import com.coav.gui.model.Flight;
import com.coav.gui.service.FlightStateStore;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(FlightController.class)
class FlightControllerTest {

    @Autowired
    MockMvc mvc;

    @MockBean
    FlightStateStore flightStateStore;

    @Test
    void getFlights_returnsOkWithFlightData() throws Exception {
        Flight f = Flight.builder()
            .flightId("C100-CLB").latitude(69.23).longitude(17.98)
            .altitudeFt(33000).speedKnots(490)
            .contrailDetected(false).issrZone(false)
            .alert(null).timestamp("2026-06-26T10:00:00Z")
            .build();
        when(flightStateStore.getAllFlights()).thenReturn(List.of(f));

        mvc.perform(get("/api/flights"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$[0].flightId").value("C100-CLB"))
            .andExpect(jsonPath("$[0].altitudeFt").value(33000))
            .andExpect(jsonPath("$[0].issrZone").value(false));
    }

    @Test
    void getFlights_criticalFlight_returnsAlertField() throws Exception {
        Flight f = Flight.builder()
            .flightId("S200-CRZ").latitude(69.22).longitude(18.00)
            .altitudeFt(34000).speedKnots(495)
            .contrailDetected(true).issrZone(true)
            .alert("CRITICAL").timestamp("2026-06-26T10:00:00Z")
            .build();
        when(flightStateStore.getAllFlights()).thenReturn(List.of(f));

        mvc.perform(get("/api/flights"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$[0].alert").value("CRITICAL"))
            .andExpect(jsonPath("$[0].contrailDetected").value(true));
    }

    @Test
    void getFlights_emptyState_returnsEmptyArray() throws Exception {
        when(flightStateStore.getAllFlights()).thenReturn(List.of());

        mvc.perform(get("/api/flights"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$").isArray())
            .andExpect(jsonPath("$").isEmpty());
    }

    @Test
    void getIssrZones_returnsTwoStaticZones() throws Exception {
        // FlightStateStore.ISSR_ZONES is a static final — available even when bean is mocked
        mvc.perform(get("/api/issr-zones"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.length()").value(2))
            .andExpect(jsonPath("$[0].id").value("ALPHA"))
            .andExpect(jsonPath("$[0].minLat").value(69.10))
            .andExpect(jsonPath("$[0].severity").value("CRITICAL"))
            .andExpect(jsonPath("$[1].id").value("BRAVO"));
    }
}
