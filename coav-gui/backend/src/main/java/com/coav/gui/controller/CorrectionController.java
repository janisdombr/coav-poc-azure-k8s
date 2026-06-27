package com.coav.gui.controller;

import com.coav.gui.model.Correction;
import com.coav.gui.model.CorrectionResult;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
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

    // OWASP A03:2021-Injection — @Valid enforces pattern/size constraints from Correction model
    @PostMapping("/correction")
    public ResponseEntity<CorrectionResult> postCorrection(@Valid @RequestBody Correction correction) {
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
}
