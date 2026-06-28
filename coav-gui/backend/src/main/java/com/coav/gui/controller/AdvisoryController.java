package com.coav.gui.controller;

import com.coav.gui.model.Advisory;
import com.coav.gui.service.AdvisoryService;
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

@RestController
@RequestMapping("/api/advisory")
@CrossOrigin(origins = "*")
@RequiredArgsConstructor
public class AdvisoryController {

    private final AdvisoryService advisoryService;

    @GetMapping
    public Collection<Advisory> getPending() {
        return advisoryService.getPendingAdvisories();
    }

    // OWASP A03 — advisory ID validated to UUID format before acting on it
    @PostMapping("/accept")
    public ResponseEntity<Void> accept(@RequestBody AdvisoryDecision body) {
        return advisoryService.accept(body.getAdvisoryId())
                ? ResponseEntity.ok().build()
                : ResponseEntity.notFound().build();
    }

    @PostMapping("/reject")
    public ResponseEntity<Void> reject(@RequestBody AdvisoryDecision body) {
        return advisoryService.reject(body.getAdvisoryId())
                ? ResponseEntity.ok().build()
                : ResponseEntity.notFound().build();
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
