package com.coav.gui.service;

import com.coav.gui.model.Flight;
import com.coav.gui.model.IssrZone;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.messaging.simp.SimpMessagingTemplate;

import java.util.Collection;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;

@ExtendWith(MockitoExtension.class)
class FlightStateStoreTest {

    @Mock
    SimpMessagingTemplate messagingTemplate;

    @Mock
    AdvisoryService advisoryService;

    @InjectMocks
    FlightStateStore store;

    // --- ISSR zone constants (single source of truth) ---

    @Test
    void issrZones_hasTwoZones() {
        assertThat(FlightStateStore.ISSR_ZONES).hasSize(2);
    }

    @Test
    void issrZones_alphaMatchesEmulatorPyCriticalZones() {
        IssrZone alpha = FlightStateStore.ISSR_ZONES.get(0);
        assertThat(alpha.getId()).isEqualTo("ALPHA");
        assertThat(alpha.getMinLat()).isEqualTo(50.20);
        assertThat(alpha.getMaxLat()).isEqualTo(51.00);
        assertThat(alpha.getMinLon()).isEqualTo(3.80);
        assertThat(alpha.getMaxLon()).isEqualTo(5.40);
        assertThat(alpha.getMinAlt()).isEqualTo(33000);
        assertThat(alpha.getMaxAlt()).isEqualTo(38000);
        assertThat(alpha.getSeverity()).isEqualTo("CRITICAL");
    }

    @Test
    void issrZones_bravoMatchesEmulatorPyCriticalZones() {
        IssrZone bravo = FlightStateStore.ISSR_ZONES.get(1);
        assertThat(bravo.getId()).isEqualTo("BRAVO");
        assertThat(bravo.getMinLat()).isEqualTo(51.30);
        assertThat(bravo.getMaxLat()).isEqualTo(52.50);
        assertThat(bravo.getMinLon()).isEqualTo(5.80);
        assertThat(bravo.getMaxLon()).isEqualTo(8.20);
        assertThat(bravo.getMinAlt()).isEqualTo(31000);
        assertThat(bravo.getMaxAlt()).isEqualTo(37000);
    }

    // --- Zone detection ---

    @Test
    void isInsideIssrZone_detectsAlphaCenter() {
        // Zone Alpha center: lat 50.60, lon 4.60, FL355
        assertThat(store.isInsideIssrZone(50.60, 4.60, 35500)).isTrue();
    }

    @Test
    void isInsideIssrZone_detectsBravoCenter() {
        // Zone Bravo center: lat 51.90, lon 7.00, FL340
        assertThat(store.isInsideIssrZone(51.90, 7.00, 34000)).isTrue();
    }

    @Test
    void isInsideIssrZone_rejectsOutsideAllZones() {
        assertThat(store.isInsideIssrZone(48.00, 2.00, 30000)).isFalse();
    }

    @Test
    void isInsideIssrZone_rejectsBelowMinAltitude() {
        assertThat(store.isInsideIssrZone(50.60, 4.60, 20000)).isFalse();
    }

    @Test
    void isInsideIssrZone_rejectsAboveMaxAltitude() {
        assertThat(store.isInsideIssrZone(50.60, 4.60, 40000)).isFalse();
    }

    @Test
    void isInsideIssrZone_acceptsAlphaExactMinBoundary() {
        assertThat(store.isInsideIssrZone(50.20, 3.80, 33000)).isTrue();
    }

    @Test
    void isInsideIssrZone_acceptsAlphaExactMaxBoundary() {
        assertThat(store.isInsideIssrZone(51.00, 5.40, 38000)).isTrue();
    }

    @Test
    void isInsideIssrZone_rejectsJustOutsideAlphaLat() {
        assertThat(store.isInsideIssrZone(51.01, 4.60, 35500)).isFalse();
    }

    // --- State management ---

    @Test
    void updateFlight_storedAndRetrievable() {
        Flight f = Flight.builder().flightId("C100-CLB")
            .latitude(69.23).longitude(17.98).altitudeFt(33000)
            .speedKnots(490).timestamp("2026-06-26T10:00:00Z").build();
        store.updateFlight(f);
        assertThat(store.getAllFlights()).hasSize(1);
        assertThat(store.getAllFlights().iterator().next().getFlightId()).isEqualTo("C100-CLB");
    }

    @Test
    void updateFlight_overwritesSameFlightId() {
        Flight v1 = Flight.builder().flightId("C100-CLB").altitudeFt(33000)
            .latitude(69.23).longitude(17.98).speedKnots(490).timestamp("t1").build();
        Flight v2 = Flight.builder().flightId("C100-CLB").altitudeFt(35000)
            .latitude(69.24).longitude(17.99).speedKnots(491).timestamp("t2").build();
        store.updateFlight(v1);
        store.updateFlight(v2);
        assertThat(store.getAllFlights()).hasSize(1);
        assertThat(store.getAllFlights().iterator().next().getAltitudeFt()).isEqualTo(35000);
    }

    // --- WebSocket broadcast ---

    @Test
    void broadcastState_sendsWhenFlightsPresent() {
        store.updateFlight(Flight.builder().flightId("C100-CLB")
            .latitude(69.23).longitude(17.98).altitudeFt(33000)
            .speedKnots(490).timestamp("t").build());
        store.broadcastState();
        verify(messagingTemplate).convertAndSend(eq("/topic/flights"), any(Collection.class));
    }

    @Test
    void broadcastState_skipsWhenEmpty() {
        store.broadcastState();
        verifyNoInteractions(messagingTemplate);
    }
}
