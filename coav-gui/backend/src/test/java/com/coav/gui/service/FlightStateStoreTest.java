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
import java.util.List;

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
    void issrZones_hasTwoFallbackZones() {
        assertThat(store.getIssrZones()).hasSize(2);
    }

    @Test
    void issrZones_alphaMatchesEmulatorPyCriticalZones() {
        IssrZone alpha = store.getIssrZones().get(0);
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
        IssrZone bravo = store.getIssrZones().get(1);
        assertThat(bravo.getId()).isEqualTo("BRAVO");
        assertThat(bravo.getMinLat()).isEqualTo(51.30);
        assertThat(bravo.getMaxLat()).isEqualTo(52.50);
        assertThat(bravo.getMinLon()).isEqualTo(5.80);
        assertThat(bravo.getMaxLon()).isEqualTo(8.20);
        assertThat(bravo.getMinAlt()).isEqualTo(31000);
        assertThat(bravo.getMaxAlt()).isEqualTo(37000);
    }

    @Test
    void updateIssrZones_replacesActive() {
        IssrZone dynamic = IssrZone.builder()
            .id("Dynamic-A").label("Dynamic Zone A (RHi 130%)")
            .minLat(50.0).maxLat(52.0).minLon(4.0).maxLon(7.0)
            .minAlt(32_000).maxAlt(36_000).severity("CRITICAL").build();
        store.updateIssrZones(List.of(dynamic));
        assertThat(store.getIssrZones()).hasSize(1);
        assertThat(store.getIssrZones().get(0).getId()).isEqualTo("Dynamic-A");
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

    // --- Alert enrichment (P1: geometry-only — WARNING no longer exists) ---
    // Contract: inside ISSR zone → CRITICAL; trajectory enters zone in <20 min
    // → APPROACHING; otherwise alert is null. The camera contrail flag NEVER
    // influences the flight alert (decoupled verification channel).

    private Flight stored(String flightId) {
        return store.getAllFlights().stream()
            .filter(f -> f.getFlightId().equals(flightId))
            .findFirst().orElseThrow();
    }

    @Test
    void enrichAlert_insideZone_setsCritical() {
        // Zone Alpha center, FL350 — producer flag issrZone mirrors geometry
        store.updateFlight(Flight.builder().flightId("CRIT1")
            .latitude(50.60).longitude(4.60).altitudeFt(35000)
            .speedKnots(470).heading(51.0)
            .issrZone(true).contrailDetected(false)
            .timestamp("t").build());
        Flight f = stored("CRIT1");
        assertThat(f.getAlert()).isEqualTo("CRITICAL");
        assertThat(f.getApproachingZoneId()).isNull();
        assertThat(f.getApproachingMinutes()).isNull();
    }

    @Test
    void enrichAlert_insideZone_criticalEvenWithoutContrailFlag() {
        // False negative from the camera channel must NOT suppress the alert
        store.updateFlight(Flight.builder().flightId("CRIT2")
            .latitude(51.90).longitude(7.00).altitudeFt(34000)
            .speedKnots(460).heading(90.0)
            .issrZone(true).contrailDetected(false)
            .timestamp("t").build());
        assertThat(stored("CRIT2").getAlert()).isEqualTo("CRITICAL");
    }

    @Test
    void enrichAlert_contrailFlagAlone_neverCreatesAlert() {
        // contrail_detected=true, but far from every zone and heading away:
        // alert stays null — geometry is the only alert source (P1)
        store.updateFlight(Flight.builder().flightId("CTR1")
            .latitude(48.00).longitude(2.00).altitudeFt(35000)
            .speedKnots(470).heading(180.0)
            .issrZone(false).contrailDetected(true)
            .timestamp("t").build());
        assertThat(stored("CTR1").getAlert()).isNull();
    }

    @Test
    void enrichAlert_producerPresetAlertIsOverridden() {
        // Legacy producers could send WARNING — enrichAlert must override it;
        // WARNING can never survive into the store
        store.updateFlight(Flight.builder().flightId("LEG1")
            .latitude(48.00).longitude(2.00).altitudeFt(35000)
            .speedKnots(470).heading(180.0)
            .issrZone(false).contrailDetected(true)
            .alert("WARNING")
            .timestamp("t").build());
        assertThat(stored("LEG1").getAlert()).isNull();
    }

    @Test
    void enrichAlert_headingTowardZone_setsApproachingWithZoneAndEta() {
        // 0.40° east of Zone Alpha (maxLon 5.40), heading due west at 480 kt:
        // lon step = 480/3600/cos(50.6°) ≈ 0.21°/min → enters at minute 2
        store.updateFlight(Flight.builder().flightId("APP1")
            .latitude(50.60).longitude(5.80).altitudeFt(35000)
            .speedKnots(480).heading(270.0)
            .issrZone(false).contrailDetected(false)
            .timestamp("t").build());
        Flight f = stored("APP1");
        assertThat(f.getAlert()).isEqualTo("APPROACHING");
        assertThat(f.getApproachingZoneId()).isEqualTo("ALPHA");
        assertThat(f.getApproachingMinutes()).isBetween(1, 3);
    }

    @Test
    void enrichAlert_headingAwayFromZone_noAlert() {
        // Same position as APP1 but heading due east — moving away
        store.updateFlight(Flight.builder().flightId("AWY1")
            .latitude(50.60).longitude(5.80).altitudeFt(35000)
            .speedKnots(480).heading(90.0)
            .issrZone(false).contrailDetected(false)
            .timestamp("t").build());
        assertThat(stored("AWY1").getAlert()).isNull();
    }

    @Test
    void enrichAlert_entryBeyond20MinuteHorizon_noAlert() {
        // 4.6° east of Zone Alpha at 480 kt ≈ 22 min to entry — beyond horizon
        store.updateFlight(Flight.builder().flightId("FAR1")
            .latitude(50.60).longitude(10.00).altitudeFt(35000)
            .speedKnots(480).heading(270.0)
            .issrZone(false).contrailDetected(false)
            .timestamp("t").build());
        assertThat(stored("FAR1").getAlert()).isNull();
    }

    @Test
    void enrichAlert_approachAtWrongAltitude_noAlert() {
        // Trajectory crosses Zone Alpha laterally but FL400 is above its ceiling
        store.updateFlight(Flight.builder().flightId("ALT1")
            .latitude(50.60).longitude(5.80).altitudeFt(40000)
            .speedKnots(480).heading(270.0)
            .issrZone(false).contrailDetected(false)
            .timestamp("t").build());
        assertThat(stored("ALT1").getAlert()).isNull();
    }

    @Test
    void updateFlight_forwardsEnrichedFlightToAdvisoryService() {
        store.updateFlight(Flight.builder().flightId("APP2")
            .latitude(50.60).longitude(5.80).altitudeFt(35000)
            .speedKnots(480).heading(270.0)
            .issrZone(false).contrailDetected(false)
            .timestamp("t").build());
        verify(advisoryService).onFlightUpdate(
            org.mockito.ArgumentMatchers.argThat(f ->
                "APPROACHING".equals(f.getAlert())
                    && "ALPHA".equals(f.getApproachingZoneId())),
            org.mockito.ArgumentMatchers.anyList());
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
