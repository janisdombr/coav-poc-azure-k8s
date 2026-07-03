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
     *
     * Advisory is generated when a flight is APPROACHING (trajectory will enter ISSR zone)
     * OR WARNING (contrail detected outside zone — FDO should review FL assignment).
     *
     * Advisory is cleared when:
     *   - CRITICAL: flight entered the zone (ATCO takes over with direct correction)
     *   - null:     contrail gone, no longer a risk
     */
    public void onFlightUpdate(Flight flight) {
        boolean isApproaching = "APPROACHING".equals(flight.getAlert());
        boolean isWarning     = "WARNING".equals(flight.getAlert());
        boolean isCritical    = "CRITICAL".equals(flight.getAlert());

        if (isApproaching || isWarning) {
            // Skip if FDO recently decided on an advisory for this flight (accept or reject)
            Instant cooldown = cooldownUntil.get(flight.getFlightId());
            if (cooldown != null) {
                if (Instant.now().isBefore(cooldown)) return;
                cooldownUntil.remove(flight.getFlightId());
            }
            // Generate once; putIfAbsent ignores subsequent ticks for the same flight.
            Advisory prev = pending.putIfAbsent(flight.getFlightId(), generate(flight));
            if (prev == null) {
                broadcast();
            }
        } else if (isCritical || flight.getAlert() == null) {
            // Entered zone (ATCO handles it) or contrail cleared — remove advisory
            if (pending.remove(flight.getFlightId()) != null) {
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

    private Advisory generate(Flight flight) {
        int currentFl = flight.getAltitudeFt() / 100;
        int flUp      = ((currentFl + 20) / 10) * 10;
        int flDown    = ((currentFl - 20) / 10) * 10;

        String text;
        if ("APPROACHING".equals(flight.getAlert()) && flight.getApproachingZoneId() != null) {
            int minutes = flight.getApproachingMinutes() != null ? flight.getApproachingMinutes() : 0;
            text = String.format(
                "%s approaching Zone %s in %d min at FL%d. Advised FL%d or FL%d.",
                flight.getFlightId(), flight.getApproachingZoneId(), minutes, currentFl, flUp, flDown
            );
        } else {
            // WARNING: contrail detected outside ISSR zone
            text = String.format(
                "%s contrail detected at FL%d. Recommend FL%d or FL%d to reduce contrail formation.",
                flight.getFlightId(), currentFl, flUp, flDown
            );
        }

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
