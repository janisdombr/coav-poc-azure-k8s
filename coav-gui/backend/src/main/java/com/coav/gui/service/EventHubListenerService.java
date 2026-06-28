package com.coav.gui.service;

import com.azure.messaging.eventhubs.EventHubClientBuilder;
import com.azure.messaging.eventhubs.EventHubConsumerClient;
import com.azure.messaging.eventhubs.models.EventPosition;
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
    private final ObjectMapper objectMapper;

    // Partial state for stream join: ADSB_TELEMETRY + EDGE_VISION_AI keyed by flight_id
    // Mirrors the join logic in backend/main.py evaluate_stream_join()
    private final Map<String, RawTelemetry> adsbState = new ConcurrentHashMap<>();
    private final Map<String, RawTelemetry> aiState   = new ConcurrentHashMap<>();

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
        try (EventHubConsumerClient client = new EventHubClientBuilder()
                .connectionString(connectionString)
                .consumerGroup(EventHubClientBuilder.DEFAULT_CONSUMER_GROUP_NAME)
                .buildConsumerClient()) {

            List<String> partitionIds = new ArrayList<>();
            client.getPartitionIds().forEach(partitionIds::add);
            log.info("[EVENT HUB] Partitions: {}", partitionIds);

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
        } catch (Exception e) {
            log.error("[EVENT HUB] Consumer error: {}", e.getMessage(), e);
        }
    }

    private void processEvent(String json) {
        try {
            RawTelemetry raw = objectMapper.readValue(json, RawTelemetry.class);

            if ("ADSB_TELEMETRY".equals(raw.getMessageType())) {
                adsbState.put(raw.getFlightId(), raw);
            } else if ("EDGE_VISION_AI".equals(raw.getMessageType())) {
                aiState.put(raw.getFlightId(), raw);
            }

            // Stream join: update Flight only when ADSB position data is available
            RawTelemetry adsb = adsbState.get(raw.getFlightId());
            if (adsb == null) return;

            RawTelemetry ai = aiState.get(raw.getFlightId());
            boolean inIssr   = store.isInsideIssrZone(adsb.getLatitude(), adsb.getLongitude(), adsb.getAltitudeFt());
            boolean contrail = ai != null && Boolean.TRUE.equals(ai.getContrailDetected());
            String alert     = (contrail && inIssr) ? "CRITICAL" : contrail ? "WARNING" : null;

            log.debug("[HOT PATH] {} | ISSR={} contrail={} alert={}", adsb.getFlightId(), inIssr, contrail, alert);

            store.updateFlight(Flight.builder()
                .flightId(adsb.getFlightId())
                .latitude(adsb.getLatitude())
                .longitude(adsb.getLongitude())
                .altitudeFt(adsb.getAltitudeFt())
                .speedKnots(adsb.getSpeedKnots())
                .heading(adsb.getHeading() != null ? adsb.getHeading() : 0.0)
                .contrailDetected(contrail)
                .issrZone(inIssr)
                .alert(alert)
                .timestamp(adsb.getTimestamp() != null ? adsb.getTimestamp() : Instant.now().toString())
                .build());

        } catch (Exception e) {
            log.warn("[EVENT HUB] Failed to parse event: {}", e.getMessage());
        }
    }
}
