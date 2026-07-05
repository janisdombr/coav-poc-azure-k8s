package com.coav.gui.service;

import com.coav.gui.model.Camera;
import com.coav.gui.model.CameraVerification;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * Holds the latest verification state per camera_id — the camera-keyed
 * counterpart of FlightStateStore. Same 5-minute TTL, same 2-second
 * WebSocket broadcast cadence (topic /topic/cameras).
 */
@Service
@Slf4j
@RequiredArgsConstructor
public class CameraStore {

    // Single static source of truth for the planned camera network.
    // emulator.py keeps its own copy of these values — keep them in sync
    // (same convention as FlightStateStore.ISSR zones).
    public static final List<Camera> CAMERAS = List.of(
        new Camera("CAM-ALPHA", 50.60, 4.60, 20.0),
        new Camera("CAM-BRAVO", 51.90, 7.00, 20.0),
        new Camera("CAM-EHBK",  50.92, 5.77, 20.0),
        new Camera("CAM-NORTH", 52.30, 6.50, 20.0)
    );

    // Whitelist of known camera IDs — reject anything outside the planned network so an
    // untrusted producer cannot inflate the state maps with unlimited distinct keys (memory-exhaustion DoS).
    private static final Set<String> KNOWN_CAMERAS =
        CAMERAS.stream().map(Camera::id).collect(Collectors.toUnmodifiableSet());

    private static final Pattern CAMERA_ID_PATTERN = Pattern.compile("[A-Z0-9-]{1,32}");
    // A <=256px binary PNG mask is a few KB; anything near this cap is out of contract
    private static final int MAX_MASK_B64_CHARS = 262_144;
    // frame_ref contract (mirror of emulator.py EdgeVisionAI): lowercase slug, <=64 chars
    private static final Pattern FRAME_REF_PATTERN = Pattern.compile("[a-z0-9_-]{1,64}");
    // Upper bound on connected-component counts (mirror of emulator.py le=500)
    private static final int MAX_CONTRAIL_COUNT = 500;

    private final SimpMessagingTemplate messagingTemplate;

    private final Map<String, CameraVerification> verifications = new ConcurrentHashMap<>();
    private final Map<String, Instant>            lastSeen      = new ConcurrentHashMap<>();

    /**
     * OWASP A03: Event Hub payloads are untrusted input — reject anything
     * outside the EDGE_VISION_AI contract instead of storing/broadcasting it.
     */
    public void updateVerification(CameraVerification v) {
        if (v == null || v.getCameraId() == null
                || !CAMERA_ID_PATTERN.matcher(v.getCameraId()).matches()) {
            log.warn("[CAMERA] Rejected verification: invalid camera_id");
            return;
        }
        // Fail closed against the known-camera whitelist (bounds distinct map keys to the network size)
        if (!KNOWN_CAMERAS.contains(v.getCameraId())) {
            log.warn("[CAMERA] Rejected verification: unknown camera_id");
            return;
        }
        if (v.getMaskPngB64() != null && v.getMaskPngB64().length() > MAX_MASK_B64_CHARS) {
            log.warn("[CAMERA] Rejected verification from {}: mask exceeds {} chars",
                v.getCameraId(), MAX_MASK_B64_CHARS);
            return;
        }
        if (v.getFrameRef() != null && !FRAME_REF_PATTERN.matcher(v.getFrameRef()).matches()) {
            log.warn("[CAMERA] Rejected verification from {}: invalid frame_ref", v.getCameraId());
            return;
        }
        if (outsideUnitRange(v.getConfidence()) || outsideUnitRange(v.getContrailPixelRatio())
                || negative(v.getContrailCount()) || negative(v.getNewContrailCount())
                || aboveMax(v.getContrailCount()) || aboveMax(v.getNewContrailCount())) {
            log.warn("[CAMERA] Rejected verification from {}: value out of range", v.getCameraId());
            return;
        }

        verifications.put(v.getCameraId(), v);
        lastSeen.put(v.getCameraId(), Instant.now());
    }

    public Collection<CameraVerification> getVerifications() {
        Instant cutoff = Instant.now().minus(5, ChronoUnit.MINUTES);
        return verifications.entrySet().stream()
            .filter(e -> lastSeen.getOrDefault(e.getKey(), Instant.EPOCH).isAfter(cutoff))
            .map(Map.Entry::getValue)
            .toList();
    }

    @Scheduled(fixedRate = 2000)
    public void broadcastState() {
        evictExpired();
        Collection<CameraVerification> active = getVerifications();
        if (!active.isEmpty()) {
            messagingTemplate.convertAndSend("/topic/cameras", active);
        }
    }

    // Physically remove stale keys from both maps so memory stays bounded even for known cameras
    // (getVerifications only filters at read time — it does not free the entries).
    private void evictExpired() {
        Instant cutoff = Instant.now().minus(5, ChronoUnit.MINUTES);
        lastSeen.entrySet().removeIf(e -> {
            if (e.getValue().isBefore(cutoff)) {
                verifications.remove(e.getKey());
                return true;
            }
            return false;
        });
    }

    private static boolean outsideUnitRange(Double value) {
        return value != null && (value < 0.0 || value > 1.0);
    }

    private static boolean negative(Integer value) {
        return value != null && value < 0;
    }

    private static boolean aboveMax(Integer value) {
        return value != null && value > MAX_CONTRAIL_COUNT;
    }
}
