package com.coav.gui.service;

import com.azure.messaging.eventhubs.EventHubClientBuilder;
import com.azure.messaging.eventhubs.EventHubConsumerClient;
import com.azure.messaging.eventhubs.models.EventPosition;
import com.coav.gui.model.CameraVerification;
import com.coav.gui.model.Flight;
import com.coav.gui.model.RawTelemetry;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.DisposableBean;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;
import org.springframework.beans.factory.annotation.Value;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;

@Service
@Profile("!mock")
@Slf4j
@RequiredArgsConstructor
public class EventHubListenerService implements ApplicationRunner, DisposableBean {

    @Value("${eventhub.connection-string:}")
    private String connectionString;

    private final FlightStateStore store;
    private final CameraStore cameraStore;
    private final ObjectMapper objectMapper;

    private final AtomicBoolean running = new AtomicBoolean(false);
    private volatile Thread consumerThread;

    @Override
    public void run(ApplicationArguments args) {
        if (connectionString == null || connectionString.isBlank()) {
            log.warn("[EVENT HUB] CONN_STR not set — listener not started. " +
                     "For local dev use: --spring.profiles.active=mock");
            return;
        }
        running.set(true);
        consumerThread = Thread.ofVirtual().start(this::consume);
        log.info("[EVENT HUB] Consumer started on namespace: {}",
            connectionString.split(";")[0]);
    }

    @Override
    public void destroy() {
        running.set(false);
        if (consumerThread != null) consumerThread.interrupt();
    }

    private void consume() {
        // Reconnect loop: if the AMQP consumer fails (e.g. "max receivers per partition"
        // after container restarts), wait for Azure to release stale links, then retry.
        // Azure Event Hub Standard: max 5 receivers per partition per consumer group;
        // a 30-second pause is enough for Azure to expire unreleased AMQP links.
        int  attempt   = 0;
        long backoffMs = 5_000;

        while (running.get() && !Thread.currentThread().isInterrupted()) {
            attempt++;
            log.info("[EVENT HUB] Connecting (attempt {}) …", attempt);
            try {
                consumeOnce();
                // consumeOnce() returns only on clean shutdown (running=false)
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                break;
            } catch (Exception e) {
                log.error("[EVENT HUB] Consumer error (attempt {}): {}", attempt, e.getMessage());
                if (!running.get()) break;
                log.info("[EVENT HUB] Reconnecting in {} s …", backoffMs / 1000);
                try { Thread.sleep(backoffMs); } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt(); break;
                }
                backoffMs = Math.min(backoffMs * 2, 60_000);  // cap at 60 s
            }
        }
        log.info("[EVENT HUB] Consumer stopped after {} attempt(s).", attempt);
    }

    private void consumeOnce() throws Exception {
        try (EventHubConsumerClient client = new EventHubClientBuilder()
                .connectionString(connectionString)
                .consumerGroup(EventHubClientBuilder.DEFAULT_CONSUMER_GROUP_NAME)
                .buildConsumerClient()) {

            List<String> partitionIds = new ArrayList<>();
            client.getPartitionIds().forEach(partitionIds::add);
            log.info("[EVENT HUB] Connected. Partitions: {}", partitionIds);

            // Start from events enqueued within the last 15 minutes — skip stale history
            Instant cutoffEnqueueTime = Instant.now().minus(java.time.Duration.ofMinutes(15));
            Map<String, EventPosition> positions = new ConcurrentHashMap<>();
            partitionIds.forEach(id ->
                positions.put(id, EventPosition.fromEnqueuedTime(cutoffEnqueueTime)));

            while (running.get() && !Thread.currentThread().isInterrupted()) {
                for (String partitionId : partitionIds) {
                    client.receiveFromPartition(
                            partitionId, 50, positions.get(partitionId),
                            java.time.Duration.ofMillis(500))
                        .forEach(pe -> {
                            positions.put(partitionId,
                                EventPosition.fromSequenceNumber(
                                    pe.getData().getSequenceNumber(), false));
                            processEvent(pe.getData().getBodyAsString());
                        });
                }
            }
            // try-with-resources calls client.close() → AMQP link released cleanly before next attempt
        }
    }

    // Two decoupled channels (P1): ADSB_TELEMETRY is flight-keyed and drives alerts
    // via ISSR geometry only; EDGE_VISION_AI is camera-keyed ground verification.
    // No stream join — contrail-to-flight attribution is deferred to P2.
    private void processEvent(String json) {
        try {
            RawTelemetry raw = objectMapper.readValue(json, RawTelemetry.class);

            if ("EDGE_VISION_AI".equals(raw.getMessageType())) {
                processCameraEvent(raw);
            } else if ("ADSB_TELEMETRY".equals(raw.getMessageType())) {
                processAdsbEvent(raw);
            }
        } catch (Exception e) {
            log.warn("[EVENT HUB] Failed to parse event: {}", e.getMessage());
        }
    }

    private void processAdsbEvent(RawTelemetry raw) {
        // OWASP A03: Event Hub payloads are untrusted — skip messages missing key/position
        if (raw.getFlightId() == null || raw.getLatitude() == null
                || raw.getLongitude() == null || raw.getAltitudeFt() == null) {
            log.warn("[EVENT HUB] Skipped ADSB_TELEMETRY with missing flight_id/position");
            return;
        }

        boolean inIssr = store.isInsideIssrZone(
            raw.getLatitude(), raw.getLongitude(), raw.getAltitudeFt());
        log.debug("[HOT PATH] {} | ISSR={}", raw.getFlightId(), inIssr);

        // Alert is left null here — FlightStateStore.enrichAlert() derives it from
        // ISSR geometry alone (CRITICAL inside, APPROACHING if entry <20 min).
        store.updateFlight(Flight.builder()
            .flightId(raw.getFlightId())
            .latitude(raw.getLatitude())
            .longitude(raw.getLongitude())
            .altitudeFt(raw.getAltitudeFt())
            .speedKnots(raw.getSpeedKnots() != null ? raw.getSpeedKnots() : 0)
            .heading(raw.getHeading() != null ? raw.getHeading() : 0.0)
            .issrZone(inIssr)
            .timestamp(raw.getTimestamp() != null ? raw.getTimestamp() : Instant.now().toString())
            .build());
    }

    private void processCameraEvent(RawTelemetry raw) {
        // CameraStore validates the payload (OWASP A03) before storing/broadcasting
        cameraStore.updateVerification(CameraVerification.builder()
            .cameraId(raw.getCameraId())
            .timestamp(raw.getTimestamp() != null ? raw.getTimestamp() : Instant.now().toString())
            .contrailDetected(Boolean.TRUE.equals(raw.getContrailDetected()))
            .confidence(raw.getConfidence())
            .contrailPixelRatio(raw.getContrailPixelRatio())
            .contrailCount(raw.getContrailCount())
            .newContrailCount(raw.getNewContrailCount())
            .frameRef(raw.getFrameRef())
            .maskPngB64(raw.getMaskPngB64())
            .build());
    }
}
