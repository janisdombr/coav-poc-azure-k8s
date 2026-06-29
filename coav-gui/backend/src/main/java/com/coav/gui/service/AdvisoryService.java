package com.coav.gui.service;

import com.coav.gui.model.Advisory;
import com.coav.gui.model.Flight;
import lombok.RequiredArgsConstructor;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

@Service
@RequiredArgsConstructor
public class AdvisoryService {

    private final SimpMessagingTemplate messagingTemplate;

    // One pending advisory per flight at a time (keyed by flightId)
    private final Map<String, Advisory> pending      = new ConcurrentHashMap<>();
    // History: accepted + rejected
    private final List<Advisory>        history      = new ArrayList<>();
    // Cooldown after any FDO decision (accept OR reject): no new advisory for 5 min.
    // Prevents re-generating for holding/slow flights whose trajectory doesn't change.
    private final Map<String, Instant>  cooldownUntil = new ConcurrentHashMap<>();
    private static final Duration       DECISION_COOLDOWN = Duration.ofMinutes(5);

    /**
     * Called by FlightStateStore every time a flight is updated.
     * Auto-generates an advisory when a flight transitions to APPROACHING,
     * clears it when the flight is no longer approaching.
     */
    public void onFlightUpdate(Flight flight) {
        boolean isApproaching = "APPROACHING".equals(flight.getAlert());

        if (isApproaching) {
            // Skip if FDO recently decided on an advisory for this flight (accept or reject)
            Instant cooldown = cooldownUntil.get(flight.getFlightId());
            if (cooldown != null) {
                if (Instant.now().isBefore(cooldown)) return;
                cooldownUntil.remove(flight.getFlightId()); // cooldown expired
            }
            // Only generate once per approach (don't spam advisories)
            pending.computeIfAbsent(flight.getFlightId(), id -> {
                Advisory adv = generate(flight);
                broadcast();
                return adv;
            });
        } else {
            // Flight left the approaching state without FDO action — remove silently
            if (pending.containsKey(flight.getFlightId())) {
                pending.remove(flight.getFlightId());
                broadcast();
            }
        }
    }

    public Collection<Advisory> getPendingAdvisories() {
        return pending.values();
    }

    public record Stats(int totalGenerated, int accepted, int rejected, double avgDecisionSeconds) {}

    public Stats getStats() {
        List<Advisory> snap;
        synchronized (history) { snap = List.copyOf(history); }

        int acc = (int) snap.stream().filter(a -> "ACCEPTED".equals(a.getStatus())).count();
        int rej = (int) snap.stream().filter(a -> "REJECTED".equals(a.getStatus())).count();

        double avg = snap.stream()
            .filter(a -> a.getDecidedAt() != null)
            .mapToLong(a -> Instant.parse(a.getDecidedAt()).getEpochSecond()
                         - Instant.parse(a.getGeneratedAt()).getEpochSecond())
            .average().orElse(0.0);

        return new Stats(pending.size() + snap.size(), acc, rej, avg);
    }

    public boolean accept(String advisoryId) {
        return decide(advisoryId, "ACCEPTED");
    }

    public boolean reject(String advisoryId) {
        return decide(advisoryId, "REJECTED");
    }

    private boolean decide(String advisoryId, String status) {
        for (Map.Entry<String, Advisory> entry : pending.entrySet()) {
            if (entry.getValue().getId().equals(advisoryId)) {
                Advisory decided = entry.getValue().toBuilder()
                        .status(status)
                        .decidedAt(Instant.now().toString())
                        .build();
                String flightId = entry.getKey();
                pending.remove(flightId);
                cooldownUntil.put(flightId, Instant.now().plus(DECISION_COOLDOWN));
                synchronized (history) { history.add(decided); }
                broadcast();
                return true;
            }
        }
        return false;
    }

    // FL ranges mirroring FlightStateStore.ISSR_ZONES (avoids circular dep)
    private static final Map<String, int[]> ZONE_FL = Map.of(
        "ALPHA", new int[]{330, 380},
        "BRAVO", new int[]{310, 370}
    );

    private Advisory generate(Flight flight) {
        int currentFl = flight.getAltitudeFt() / 100;
        int flUp      = ((currentFl + 20) / 10) * 10;
        int flDown    = ((currentFl - 20) / 10) * 10;

        String zoneId  = flight.getApproachingZoneId() != null ? flight.getApproachingZoneId() : "ISSR";
        int[]  flRange = ZONE_FL.getOrDefault(zoneId, new int[]{currentFl - 20, currentFl + 20});
        int    minutes = flight.getApproachingMinutes() != null ? flight.getApproachingMinutes() : 0;

        // Format mirrors ARGOS COAV: "KLM892 Contrail ALPHA FL330-380 in 12 min. Advised FL390 or FL320."
        String text = String.format(
            "%s Contrail %s FL%d-%d in %d min. Advised FL%d or FL%d.",
            flight.getFlightId(), zoneId, flRange[0], flRange[1], minutes, flUp, flDown
        );

        return Advisory.builder()
                .id(UUID.randomUUID().toString())
                .flightId(flight.getFlightId())
                .zoneId(flight.getApproachingZoneId())
                .text(text)
                .currentFl(currentFl)
                .recommendedFlUp(flUp)
                .recommendedFlDown(flDown)
                .estimatedMinutes(flight.getApproachingMinutes())
                .status("PENDING")
                .generatedAt(Instant.now().toString())
                .decidedAt(null)
                .build();
    }

    private void broadcast() {
        messagingTemplate.convertAndSend("/topic/advisories", pending.values());
    }
}
