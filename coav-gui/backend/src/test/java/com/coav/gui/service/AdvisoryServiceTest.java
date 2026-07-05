package com.coav.gui.service;

import com.coav.gui.model.Advisory;
import com.coav.gui.model.Flight;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.messaging.simp.SimpMessagingTemplate;

import static org.assertj.core.api.Assertions.assertThat;

@ExtendWith(MockitoExtension.class)
class AdvisoryServiceTest {

    @Mock
    SimpMessagingTemplate messagingTemplate;

    @InjectMocks
    AdvisoryService service;

    private static Flight flight(String id, String alert) {
        return Flight.builder()
            .flightId(id)
            .latitude(50.60).longitude(5.80)
            .altitudeFt(35000).speedKnots(480).heading(270.0)
            .alert(alert)
            .approachingZoneId("APPROACHING".equals(alert) ? "ALPHA" : null)
            .approachingMinutes("APPROACHING".equals(alert) ? 12 : null)
            .timestamp("2026-07-05T00:00:00Z")
            .build();
    }

    // --- P1 contract: advisory is generated ONLY on APPROACHING ---

    @Test
    void approachingFlight_generatesPendingAdvisory() {
        service.onFlightUpdate(flight("KLM892", "APPROACHING"));
        assertThat(service.getPendingAdvisories()).hasSize(1);
        Advisory a = service.getPendingAdvisories().iterator().next();
        assertThat(a.getFlightId()).isEqualTo("KLM892");
        assertThat(a.getZoneId()).isEqualTo("ALPHA");
        assertThat(a.getStatus()).isEqualTo("PENDING");
        assertThat(a.getText()).contains("KLM892").contains("ALPHA").contains("12 min");
    }

    @Test
    void criticalFlight_generatesNoAdvisory() {
        service.onFlightUpdate(flight("BEL256", "CRITICAL"));
        assertThat(service.getPendingAdvisories()).isEmpty();
    }

    @Test
    void nullAlertFlight_generatesNoAdvisory() {
        service.onFlightUpdate(flight("EZY214", null));
        assertThat(service.getPendingAdvisories()).isEmpty();
    }

    @Test
    void legacyWarningAlert_generatesNoAdvisory() {
        // WARNING no longer exists in the alert contract — if it ever leaks in,
        // it must be treated like "no advisory trigger"
        service.onFlightUpdate(flight("DLH437", "WARNING"));
        assertThat(service.getPendingAdvisories()).isEmpty();
    }

    // --- Lifecycle: one advisory per flight; cleared on CRITICAL / null ---

    @Test
    void repeatedApproachingTicks_keepSingleAdvisory() {
        service.onFlightUpdate(flight("KLM892", "APPROACHING"));
        service.onFlightUpdate(flight("KLM892", "APPROACHING"));
        service.onFlightUpdate(flight("KLM892", "APPROACHING"));
        assertThat(service.getPendingAdvisories()).hasSize(1);
    }

    @Test
    void advisoryCleared_whenFlightEntersZone() {
        service.onFlightUpdate(flight("KLM892", "APPROACHING"));
        service.onFlightUpdate(flight("KLM892", "CRITICAL"));
        assertThat(service.getPendingAdvisories()).isEmpty();
    }

    @Test
    void advisoryCleared_whenTrajectoryNoLongerIntersects() {
        service.onFlightUpdate(flight("KLM892", "APPROACHING"));
        service.onFlightUpdate(flight("KLM892", null));
        assertThat(service.getPendingAdvisories()).isEmpty();
    }

    // --- FL recommendation arithmetic ---

    @Test
    void advisory_recommendsPlusAndMinus2000Ft() {
        service.onFlightUpdate(flight("KLM892", "APPROACHING"));
        Advisory a = service.getPendingAdvisories().iterator().next();
        assertThat(a.getCurrentFl()).isEqualTo(350);
        assertThat(a.getRecommendedFlUp()).isEqualTo(370);
        assertThat(a.getRecommendedFlDown()).isEqualTo(330);
    }

    // --- FDO decision + cooldown ---

    @Test
    void accept_movesAdvisoryToHistoryAndBlocksRegeneration() {
        service.onFlightUpdate(flight("KLM892", "APPROACHING"));
        String id = service.getPendingAdvisories().iterator().next().getId();

        assertThat(service.accept(id)).isTrue();
        assertThat(service.getPendingAdvisories()).isEmpty();

        // Cooldown: same still-approaching flight must not regenerate immediately
        service.onFlightUpdate(flight("KLM892", "APPROACHING"));
        assertThat(service.getPendingAdvisories()).isEmpty();

        AdvisoryService.Stats stats = service.getStats();
        assertThat(stats.accepted()).isEqualTo(1);
        assertThat(stats.rejected()).isZero();
    }

    @Test
    void reject_unknownAdvisoryId_returnsFalse() {
        assertThat(service.reject("no-such-id")).isFalse();
    }
}
