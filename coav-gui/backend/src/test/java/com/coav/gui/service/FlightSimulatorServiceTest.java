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
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

@ExtendWith(MockitoExtension.class)
class FlightSimulatorServiceTest {

    @Mock
    FlightStateStore store;

    @InjectMocks
    FlightSimulatorService service;

    @Test
    void tick_callsUpdateFlightExactlyThreeTimes() {
        service.tick();
        verify(store, times(3)).updateFlight(org.mockito.ArgumentMatchers.any(Flight.class));
    }

    @Test
    void tick_flightsHaveExpectedFields() {
        ArgumentCaptor<Flight> captor = ArgumentCaptor.forClass(Flight.class);
        service.tick();
        verify(store, times(3)).updateFlight(captor.capture());

        List<Flight> flights = captor.getAllValues();
        assertThat(flights).hasSize(3);
        flights.forEach(f -> {
            assertThat(f.getFlightId()).isNotBlank();
            assertThat(f.getTimestamp()).isNotBlank();
            assertThat(f.getSpeedKnots()).isBetween(480, 520);
            assertThat(f.getLatitude()).isBetween(60.0, 80.0);
            assertThat(f.getLongitude()).isBetween(10.0, 30.0);
        });
    }

    @Test
    void tick_flightIdsAreUnique() {
        ArgumentCaptor<Flight> captor = ArgumentCaptor.forClass(Flight.class);
        service.tick();
        verify(store, times(3)).updateFlight(captor.capture());

        List<String> ids = captor.getAllValues().stream().map(Flight::getFlightId).toList();
        assertThat(ids).doesNotHaveDuplicates();
    }

    @Test
    void tick_secondCallUpdatesPositions() {
        ArgumentCaptor<Flight> captor = ArgumentCaptor.forClass(Flight.class);
        service.tick();
        service.tick();
        verify(store, times(6)).updateFlight(captor.capture());

        List<Flight> all = captor.getAllValues();
        // First and fourth flight (same ID, different ticks) should have different coords
        assertThat(all.get(0).getLatitude()).isNotEqualTo(all.get(3).getLatitude());
    }
}
