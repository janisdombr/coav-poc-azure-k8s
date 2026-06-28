package com.coav.gui.controller;

import com.coav.gui.model.Correction;
import com.coav.gui.model.CorrectionResult;
import com.coav.gui.service.CorrectionRateLimiter;
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

        String message = String.format("ATC instruction: %s change FL to FL%d",
            correction.getFlightId(), correction.getNewAltitudeFt() / 100);

        CorrectionResult result = CorrectionResult.builder()
            .flightId(correction.getFlightId())
            .status("ACCEPTED")
            .message(message)
            .timestamp(Instant.now().toString())
            .build();

        messagingTemplate.convertAndSend("/topic/corrections", result);
        return ResponseEntity.ok(result);
    }

    // Respect X-Forwarded-For set by Azure Container Apps load balancer
    private static String resolveClientIp(HttpServletRequest request) {
        String forwarded = request.getHeader("X-Forwarded-For");
        if (forwarded != null && !forwarded.isBlank()) {
            return forwarded.split(",")[0].trim();
        }
        return request.getRemoteAddr();
    }
}
