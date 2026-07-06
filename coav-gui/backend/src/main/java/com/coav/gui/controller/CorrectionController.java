package com.coav.gui.controller;

import com.coav.gui.model.Correction;
import com.coav.gui.model.CorrectionResult;
import com.coav.gui.service.CorrectionRateLimiter;
import com.coav.gui.service.FlightStateStore;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;

@RestController
@RequestMapping("/api")
@CrossOrigin(origins = "*")
@RequiredArgsConstructor
public class CorrectionController {

    private final SimpMessagingTemplate messagingTemplate;
    private final CorrectionRateLimiter rateLimiter;
    private final FlightStateStore flightStateStore;

    // OWASP A03:2021-Injection — @Valid enforces pattern/size constraints from Correction model
    // OWASP A04:2021-Insecure Design — rate limit: 10 corrections/min per IP to prevent WebSocket flood
    @PostMapping("/correction")
    public ResponseEntity<CorrectionResult> postCorrection(
            @Valid @RequestBody Correction correction,
            HttpServletRequest request) {

        String ip = resolveClientIp(request);
        if (!rateLimiter.allow(ip)) {
            return ResponseEntity.status(HttpStatus.TOO_MANY_REQUESTS).build();
        }

        int newFl = correction.getNewAltitudeFt() / 100;
        int oldFl = flightStateStore.getAllFlights().stream()
            .filter(f -> f.getFlightId().equals(correction.getFlightId()))
            .mapToInt(f -> f.getAltitudeFt() / 100)
            .findFirst()
            .orElse(newFl);  // flight unknown or expired from store — no current FL to show

        // Decision-support wording only — the system must never read as issuing a clearance
        String message = String.format(
            "ATCO correction logged: %s FL%d → FL%d — advisory support only, not a clearance",
            correction.getFlightId(), oldFl, newFl);

        CorrectionResult result = CorrectionResult.builder()
            .flightId(correction.getFlightId())
            .status("ACCEPTED")
            .message(message)
            .timestamp(Instant.now().toString())
            .build();

        messagingTemplate.convertAndSend("/topic/corrections", result);
        return ResponseEntity.ok(result);
    }

    // OWASP A04 rate-limit key: Azure Container Apps appends the real client IP as the
    // LAST X-Forwarded-For hop; earlier entries are client-controlled and spoofable
    private static String resolveClientIp(HttpServletRequest request) {
        String forwarded = request.getHeader("X-Forwarded-For");
        if (forwarded != null && !forwarded.isBlank()) {
            String[] parts = forwarded.split(",");
            String last = parts[parts.length - 1].trim();
            if (!last.isEmpty()) {
                return last;
            }
        }
        return request.getRemoteAddr();
    }
}
