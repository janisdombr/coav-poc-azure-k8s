package com.coav.gui.service;

import com.coav.gui.model.Flight;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.atLeast;
import static org.mockito.Mockito.verify;

@ExtendWith(MockitoExtension.class)
class FlightSimulatorServiceTest {

    @Mock
    FlightStateStore store;

    @InjectMocks
    FlightSimulatorService service;

    @Test
    void tick_emitsAtLeastSixFlights() {
        // 4 transit (staggered, all active at tick 1) + 2 holding + 1 departure = 7
        service.tick();
        verify(store, atLeast(6)).updateFlight(org.mockito.ArgumentMatchers.any(Flight.class));
    }

    @Test
    void tick_flightsHaveExpectedFields() {
        ArgumentCaptor<Flight> captor = ArgumentCaptor.forClass(Flight.class);
        service.tick();
        verify(store, atLeast(6)).updateFlight(captor.capture());

        List<Flight> flights = captor.getAllValues();
        assertThat(flights).hasSizeGreaterThanOrEqualTo(6);
        flights.forEach(f -> {
            assertThat(f.getFlightId()).isNotBlank();
            assertThat(f.getTimestamp()).isNotBlank();
            // Speeds: transit 460-490, holding 265, departure 280-475
            assertThat(f.getSpeedKnots()).isBetween(260, 500);
            // MUAC sector + Maastricht departure area
            assertThat(f.getLatitude()).isBetween(49.0, 54.0);
            assertThat(f.getLongitude()).isBetween(2.0, 10.0);
        });
    }

    @Test
    void tick_flightIdsAreUnique() {
        ArgumentCaptor<Flight> captor = ArgumentCaptor.forClass(Flight.class);
        service.tick();
        verify(store, atLeast(6)).updateFlight(captor.capture());

        List<String> ids = captor.getAllValues().stream().map(Flight::getFlightId).toList();
        assertThat(ids).doesNotHaveDuplicates();
    }

    @Test
    void tick_secondCallUpdatesTransitPositions() {
        ArgumentCaptor<Flight> captor = ArgumentCaptor.forClass(Flight.class);
        service.tick();
        service.tick();
        verify(store, atLeast(12)).updateFlight(captor.capture());

        List<Flight> all = captor.getAllValues();
        // First transit flight (index 0) should have moved between tick 1 and tick 2
        // Collect the two appearances of the same flightId
        String firstId = all.get(0).getFlightId();
        List<Flight> appearances = all.stream()
            .filter(f -> f.getFlightId().equals(firstId))
            .toList();
        assertThat(appearances).hasSize(2);
        assertThat(appearances.get(0).getLatitude())
            .isNotEqualTo(appearances.get(1).getLatitude());
    }

    @Test
    void tick_emitsNoPresetAlert_enrichmentIsStoreResponsibility() {
        // P1 contract: alerts are derived from ISSR geometry ONLY, inside
        // FlightStateStore.enrichAlert(). The simulator must emit alert=null —
        // in particular it must never fabricate WARNING from the contrail flag.
        ArgumentCaptor<Flight> captor = ArgumentCaptor.forClass(Flight.class);
        service.tick();
        verify(store, atLeast(6)).updateFlight(captor.capture());
        captor.getAllValues().forEach(f -> assertThat(f.getAlert()).isNull());
    }

    @Test
    void tick_contrailFlagDoesNotImplyAlert() {
        // contrailDetected is simulation flavour (random 12% outside zones) and
        // is decoupled from alerts: even flights with the flag carry alert=null.
        ArgumentCaptor<Flight> captor = ArgumentCaptor.forClass(Flight.class);
        for (int i = 0; i < 30; i++) service.tick();   // enough ticks to hit the 12%
        verify(store, atLeast(6)).updateFlight(captor.capture());

        List<Flight> withContrail = captor.getAllValues().stream()
            .filter(Flight::isContrailDetected).toList();
        assertThat(withContrail).isNotEmpty();
        withContrail.forEach(f -> assertThat(f.getAlert()).isNull());
    }

    @Test
    void tick_issrZoneFlagMirrorsStoreGeometry() {
        // The producer flag issrZone must be exactly store.isInsideIssrZone(...)
        org.mockito.Mockito.when(store.isInsideIssrZone(
                org.mockito.ArgumentMatchers.anyDouble(),
                org.mockito.ArgumentMatchers.anyDouble(),
                org.mockito.ArgumentMatchers.anyInt()))
            .thenReturn(true);
        ArgumentCaptor<Flight> captor = ArgumentCaptor.forClass(Flight.class);
        service.tick();
        verify(store, atLeast(6)).updateFlight(captor.capture());
        captor.getAllValues().forEach(f -> assertThat(f.isIssrZone()).isTrue());
    }

    @Test
    void holdingFlights_keepSameCallsignAcrossTicks() {
        ArgumentCaptor<Flight> captor = ArgumentCaptor.forClass(Flight.class);
        service.tick();
        service.tick();
        verify(store, atLeast(12)).updateFlight(captor.capture());

        List<String> ids = captor.getAllValues().stream().map(Flight::getFlightId).toList();
        // Both holding callsigns must appear in both ticks
        assertThat(ids.stream().filter("BEL256"::equals).count()).isEqualTo(2);
        assertThat(ids.stream().filter("KLM892"::equals).count()).isEqualTo(2);
    }
}
