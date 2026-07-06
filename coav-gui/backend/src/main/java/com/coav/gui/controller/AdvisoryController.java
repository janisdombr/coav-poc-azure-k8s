package com.coav.gui.controller;

import com.coav.gui.model.Advisory;
import com.coav.gui.service.AdvisoryService;
import com.coav.gui.service.FlightStateStore;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Collection;
import java.util.Map;

@RestController
@RequestMapping("/api/advisory")
@CrossOrigin(origins = "*")
@RequiredArgsConstructor
public class AdvisoryController {

    private final AdvisoryService advisoryService;
    private final FlightStateStore flightStateStore;

    @GetMapping
    public Collection<Advisory> getPending() {
        return advisoryService.getPendingAdvisories();
    }

    // OWASP A03 — advisory ID validated to UUID format before acting on it
    @PostMapping("/accept")
    public ResponseEntity<Void> accept(@Valid @RequestBody AdvisoryDecision body) {
        return advisoryService.accept(body.getAdvisoryId())
                ? ResponseEntity.ok().build()
                : ResponseEntity.notFound().build();
    }

    @PostMapping("/reject")
    public ResponseEntity<Void> reject(@Valid @RequestBody AdvisoryDecision body) {
        return advisoryService.reject(body.getAdvisoryId())
                ? ResponseEntity.ok().build()
                : ResponseEntity.notFound().build();
    }

    @GetMapping("/stats")
    public Map<String, Object> getStats() {
        AdvisoryService.Stats s = advisoryService.getStats();
        long inIssr = flightStateStore.getAllFlights().stream()
                .filter(f -> "CRITICAL".equals(f.getAlert())).count();
        return Map.of(
            "totalGenerated",    s.totalGenerated(),
            "accepted",          s.accepted(),
            "rejected",          s.rejected(),
            "pending",           advisoryService.getPendingAdvisories().size(),
            "flightsInIssr",     inIssr,
            "avgDecisionSeconds", Math.round(s.avgDecisionSeconds())
        );
    }

    @Data
    public static class AdvisoryDecision {
        // OWASP A03 — UUID format only, prevents injection via advisory ID field
        @NotBlank
        @Size(max = 36)
        @Pattern(regexp = "^[0-9a-f\\-]{36}$")
        private String advisoryId;
    }
}
