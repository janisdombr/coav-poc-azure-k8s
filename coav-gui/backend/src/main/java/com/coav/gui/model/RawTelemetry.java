package com.coav.gui.model;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

// Deserialises JSON payloads emitted by edge-emulator/emulator.py (snake_case keys)
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class RawTelemetry {
    @JsonProperty("message_type")
    private String messageType; // "ADSB_TELEMETRY" | "EDGE_VISION_AI"
    @JsonProperty("flight_id")
    private String flightId;
    private String timestamp;
    private Double latitude;
    private Double longitude;
    @JsonProperty("altitude_ft")
    private Integer altitudeFt;
    @JsonProperty("speed_knots")
    private Integer speedKnots;
    @JsonProperty("camera_id")
    private String cameraId;
    @JsonProperty("contrail_detected")
    private Boolean contrailDetected;
    @JsonProperty("confidence_score")
    private Double confidenceScore;
}
