package com.coav.gui.service;

import com.coav.gui.model.Camera;
import com.coav.gui.model.CameraVerification;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Profile;
import org.springframework.core.io.ClassPathResource;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.io.InputStream;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Free-tier replacement for the edge emulator's camera producer.
 *
 * <p>Replays the precomputed GVCCS held-out inference bundle (real U-Net masks, computed offline —
 * the same precompute+replay data the emulator uses) straight into {@link CameraStore}, so the
 * decoupled camera-verification channel keeps working in a single-host mock deployment with
 * <strong>no Azure Event Hub and no emulator container</strong>.
 *
 * <p>Opt-in and inert by default: only instantiated when the {@code mock} profile is active
 * <em>and</em> {@code coav.mock-camera.enabled=true}. It never runs alongside the Event Hub camera
 * path ({@code EventHubListenerService} is {@code @Profile("!mock")}), and changes nothing about the
 * existing Azure deployment.
 */
@Service
@Profile("mock")
@ConditionalOnProperty(name = "coav.mock-camera.enabled", havingValue = "true")
@Slf4j
public class MockCameraService {

    private static final String BUNDLE = "mock-camera/precomputed.json";

    private final CameraStore cameraStore;
    private final ObjectMapper mapper;

    private final List<Frame> frames = new ArrayList<>();
    private final AtomicInteger tick = new AtomicInteger();
    private final Map<String, Integer> prevCount = new ConcurrentHashMap<>();

    public MockCameraService(CameraStore cameraStore, ObjectMapper mapper) {
        this.cameraStore = cameraStore;
        this.mapper = mapper;
    }

    /** One precomputed frame. {@code vizJpegB64} is the frame+mask overlay the UI renders. */
    private record Frame(String frameRef, double confidence, double pixelRatio,
                         int contrailCount, String vizJpegB64) {}

    @PostConstruct
    void load() throws Exception {
        try (InputStream in = new ClassPathResource(BUNDLE).getInputStream()) {
            JsonNode framesNode = mapper.readTree(in).get("frames");
            framesNode.fields().forEachRemaining(e -> {
                JsonNode f = e.getValue();
                frames.add(new Frame(
                    e.getKey(),
                    f.path("confidence").asDouble(),
                    f.path("pixel_ratio").asDouble(),
                    f.path("contrail_count").asInt(),
                    f.path("viz_jpeg_b64").asText(null)));
            });
        }
        log.info("[MOCK-CAMERA] Loaded {} precomputed GVCCS frames for replay", frames.size());
    }

    /**
     * Every 4 s advance the replay and push one frame to each camera. Cameras are offset into the
     * frame list so the 4 all-sky positions show different scenes. {@code CameraStore} validates and
     * broadcasts each payload exactly as it would for a real Event Hub message — the mock is upstream
     * of the same store, so the API/WebSocket contract is identical.
     */
    @Scheduled(fixedRate = 4000)
    public void replay() {
        if (frames.isEmpty()) {
            return;
        }
        int t = tick.getAndIncrement();
        List<Camera> cameras = CameraStore.CAMERAS;
        int n = frames.size();
        int stride = Math.max(1, n / cameras.size());

        for (int i = 0; i < cameras.size(); i++) {
            Camera cam = cameras.get(i);
            Frame f = frames.get(Math.floorMod(t + i * stride, n));

            // Simplified temporal delta: newly-appeared contrails vs this camera's previous frame.
            int prev = prevCount.getOrDefault(cam.id(), 0);
            int newCount = Math.max(0, f.contrailCount() - prev);
            prevCount.put(cam.id(), f.contrailCount());

            cameraStore.updateVerification(CameraVerification.builder()
                .cameraId(cam.id())
                .timestamp(Instant.now().toString())
                .contrailDetected(f.contrailCount() > 0)
                .confidence(f.confidence())
                .contrailPixelRatio(f.pixelRatio())
                .contrailCount(f.contrailCount())
                .newContrailCount(newCount)
                .frameRef(f.frameRef())
                .maskPngB64(f.vizJpegB64())
                .build());
        }
    }
}
