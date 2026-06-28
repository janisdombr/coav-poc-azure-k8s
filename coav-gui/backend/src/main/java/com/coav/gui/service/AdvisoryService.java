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
    // Rejection cooldown: flight won't get a new advisory for 5 min after FDO rejects
    private final Map<String, Instant>  rejectedUntil = new ConcurrentHashMap<>();
    private static final Duration       REJECT_COOLDOWN = Duration.ofMinutes(5);

    /**
     * Called by FlightStateStore every time a flight is updated.
     * Auto-generates an advisory when a flight transitions to APPROACHING,
     * clears it when the flight is no longer approaching.
     */
    public void onFlightUpdate(Flight flight) {
        boolean isApproaching = "APPROACHING".equals(flight.getAlert());

        if (isApproaching) {
            // Skip if FDO recently rejected an advisory for this flight
            Instant cooldown = rejectedUntil.get(flight.getFlightId());
            if (cooldown != null) {
                if (Instant.now().isBefore(cooldown)) return;
                rejectedUntil.remove(flight.getFlightId()); // cooldown expired
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
                if ("REJECTED".equals(status)) {
                    rejectedUntil.put(flightId, Instant.now().plus(REJECT_COOLDOWN));
                }
                synchronized (history) { history.add(decided); }
                broadcast();
                return true;
            }
        }
        return false;
    }

    private Advisory generate(Flight flight) {
        int currentFl    = flight.getAltitudeFt() / 100;
        int flUp         = ((currentFl + 20) / 10) * 10;   // round to nearest FL10
        int flDown       = ((currentFl - 20) / 10) * 10;

        String zoneLabel = flight.getApproachingZoneId() != null
                ? "Zone " + flight.getApproachingZoneId()
                : "ISSR zone";

        String text = String.format(
            "%s at FL%d entering %s in %d min. Recommend FL%d (+%dft) or FL%d (-%dft).",
            flight.getFlightId(), currentFl, zoneLabel, flight.getApproachingMinutes(),
            flUp, (flUp - currentFl) * 100,
            flDown, (currentFl - flDown) * 100
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
