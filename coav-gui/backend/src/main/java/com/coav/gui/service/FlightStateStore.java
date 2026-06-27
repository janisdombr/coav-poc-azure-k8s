package com.coav.gui.service;

import com.coav.gui.model.Flight;
import com.coav.gui.model.IssrZone;
import lombok.RequiredArgsConstructor;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

@Service
@RequiredArgsConstructor
public class FlightStateStore {

    private final SimpMessagingTemplate messagingTemplate;

    // ISSR zone coordinates — single source of truth mirroring
    // emulator.py CRITICAL_ZONES and backend/main.py WEATHER_GRID_ISSR
    public static final List<IssrZone> ISSR_ZONES = List.of(
        IssrZone.builder()
            .id("ALPHA").label("Zone Alpha — Radar Station")
            .minLat(69.10).maxLat(69.35).minLon(17.80).maxLon(18.20)
            .minAlt(31000).maxAlt(36000).severity("CRITICAL")
            .build(),
        IssrZone.builder()
            .id("BRAVO").label("Zone Bravo — Northeast")
            .minLat(69.40).maxLat(69.65).minLon(18.30).maxLon(18.70)
            .minAlt(33000).maxAlt(39000).severity("CRITICAL")
            .build()
    );

    private final Map<String, Flight>  flights  = new ConcurrentHashMap<>();
    private final Map<String, Instant> lastSeen = new ConcurrentHashMap<>();

    public void updateFlight(Flight flight) {
        flights.put(flight.getFlightId(), flight);
        lastSeen.put(flight.getFlightId(), Instant.now());
    }

    public Collection<Flight> getAllFlights() {
        Instant cutoff = Instant.now().minus(5, ChronoUnit.MINUTES);
        return flights.entrySet().stream()
            .filter(e -> lastSeen.getOrDefault(e.getKey(), Instant.EPOCH).isAfter(cutoff))
            .sorted((a, b) -> lastSeen.get(b.getKey()).compareTo(lastSeen.get(a.getKey())))
            .map(Map.Entry::getValue)
            .toList();
    }

    public boolean isInsideIssrZone(double lat, double lon, int alt) {
        for (IssrZone z : ISSR_ZONES) {
            if (lat >= z.getMinLat() && lat <= z.getMaxLat()
                    && lon >= z.getMinLon() && lon <= z.getMaxLon()
                    && alt >= z.getMinAlt() && alt <= z.getMaxAlt()) {
                return true;
            }
        }
        return false;
    }

    // Push current state to all WebSocket subscribers every 2s (both profiles)
    @Scheduled(fixedRate = 2000)
    public void broadcastState() {
        Collection<Flight> active = getAllFlights();
        if (!active.isEmpty()) {
            messagingTemplate.convertAndSend("/topic/flights", active);
        }
    }
}
