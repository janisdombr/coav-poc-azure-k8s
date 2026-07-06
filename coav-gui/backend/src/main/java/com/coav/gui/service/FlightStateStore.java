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
    private final AdvisoryService       advisoryService;

    // Fallback hardcoded zones — used until IssrZoneService refreshes from Open-Meteo.
    // Mirrors emulator.py CRITICAL_ZONES and backend/main.py WEATHER_GRID_ISSR.
    public static final List<IssrZone> FALLBACK_ZONES = List.of(
        IssrZone.builder()
            .id("ALPHA").label("Zone Alpha — Brussels convergence (demo: no ISSR detected)")
            .minLat(50.20).maxLat(51.00).minLon(3.80).maxLon(5.40)
            .minAlt(33000).maxAlt(38000).severity("CRITICAL").demo(true)
            .build(),
        IssrZone.builder()
            .id("BRAVO").label("Zone Bravo — Dutch-German border (demo: no ISSR detected)")
            .minLat(51.30).maxLat(52.50).minLon(5.80).maxLon(8.20)
            .minAlt(31000).maxAlt(37000).severity("CRITICAL").demo(true)
            .build()
    );

    // Replaced at runtime by IssrZoneService every 30 min; starts with hardcoded fallback.
    private volatile List<IssrZone> issrZones = FALLBACK_ZONES;

    public List<IssrZone> getIssrZones() { return issrZones; }

    public void updateIssrZones(List<IssrZone> zones) {
        issrZones = List.copyOf(zones);
    }

    // How many 1-minute steps to project forward when checking APPROACHING
    private static final int APPROACH_HORIZON_MINUTES = 20;

    private final Map<String, Flight>  flights  = new ConcurrentHashMap<>();
    private final Map<String, Instant> lastSeen = new ConcurrentHashMap<>();

    public void updateFlight(Flight flight) {
        Flight enriched = enrichAlert(flight);
        flights.put(enriched.getFlightId(), enriched);
        lastSeen.put(enriched.getFlightId(), Instant.now());
        advisoryService.onFlightUpdate(enriched, issrZones);
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
        for (IssrZone z : issrZones) {
            if (lat >= z.getMinLat() && lat <= z.getMaxLat()
                    && lon >= z.getMinLon() && lon <= z.getMaxLon()
                    && alt >= z.getMinAlt() && alt <= z.getMaxAlt()) {
                return true;
            }
        }
        return false;
    }

    @Scheduled(fixedRate = 2000)
    public void broadcastState() {
        Collection<Flight> active = getAllFlights();
        if (!active.isEmpty()) {
            messagingTemplate.convertAndSend("/topic/flights", active);
        }
    }

    // ── Trajectory projection ──────────────────────────────────────────────────

    /**
     * Single source of truth for flight alerts — derived from ISSR geometry ONLY
     * (P1: camera AI channel is decoupled and never influences flight alerts):
     * inside a zone → CRITICAL, entering within APPROACH_HORIZON_MINUTES →
     * APPROACHING, otherwise no alert. Any alert set by the producer is overridden.
     */
    private Flight enrichAlert(Flight f) {
        if (f.isIssrZone()) {
            return f.toBuilder()
                    .alert("CRITICAL")
                    .approachingZoneId(null)
                    .approachingMinutes(null)
                    .build();
        }

        ApproachResult approach = projectTrajectory(
                f.getLatitude(), f.getLongitude(), f.getAltitudeFt(),
                f.getSpeedKnots(), f.getHeading());

        if (approach != null) {
            return f.toBuilder()
                    .alert("APPROACHING")
                    .approachingZoneId(approach.zoneId())
                    .approachingMinutes(approach.minutes())
                    .build();
        }

        return f.toBuilder()
                .alert(null)
                .approachingZoneId(null)
                .approachingMinutes(null)
                .build();
    }

    /**
     * Projects flight position 1 minute at a time (flat-earth, sufficient for PoC).
     * Returns which zone it will enter and in how many minutes, or null if it won't.
     *
     * Speed in knots → 1 knot = 1 NM/h = 1/60 arc-minute of lat per minute
     *                         = 1/3600 degree of lat per minute.
     */
    private ApproachResult projectTrajectory(double lat, double lon, int alt,
                                             int speedKnots, double headingDeg) {
        double distDegPerMin = speedKnots / 3600.0;
        double headRad       = Math.toRadians(headingDeg);
        double cosLat        = Math.cos(Math.toRadians(lat));
        if (cosLat < 0.001) cosLat = 0.001;  // guard for poles

        for (int min = 1; min <= APPROACH_HORIZON_MINUTES; min++) {
            lat += distDegPerMin * Math.cos(headRad);
            lon += distDegPerMin * Math.sin(headRad) / cosLat;
            for (IssrZone z : issrZones) {
                if (lat >= z.getMinLat() && lat <= z.getMaxLat()
                        && lon >= z.getMinLon() && lon <= z.getMaxLon()
                        && alt >= z.getMinAlt() && alt <= z.getMaxAlt()) {
                    return new ApproachResult(z.getId(), min);
                }
            }
        }
        return null;
    }

    private record ApproachResult(String zoneId, int minutes) {}
}
