package com.coav.gui.model;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

// Deserialises JSON payloads emitted by edge-emulator/emulator.py (snake_case keys).
// Two disjoint contracts share this envelope:
//   ADSB_TELEMETRY  — flight-keyed (flight_id + position fields)
//   EDGE_VISION_AI  — camera-keyed (camera_id + detection fields, NO flight_id)
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class RawTelemetry {
    @JsonProperty("message_type")
    private String messageType; // "ADSB_TELEMETRY" | "EDGE_VISION_AI"
    private String timestamp;

    // ── ADSB_TELEMETRY (flight-keyed) ──
    @JsonProperty("flight_id")
    private String flightId;
    private Double latitude;
    private Double longitude;
    @JsonProperty("altitude_ft")
    private Integer altitudeFt;
    @JsonProperty("speed_knots")
    private Integer speedKnots;
    private Double heading;

    // ── EDGE_VISION_AI (camera-keyed) ──
    @JsonProperty("camera_id")
    private String cameraId;
    @JsonProperty("contrail_detected")
    private Boolean contrailDetected;
    private Double confidence;
    @JsonProperty("contrail_pixel_ratio")
    private Double contrailPixelRatio;
    @JsonProperty("contrail_count")
    private Integer contrailCount;
    @JsonProperty("new_contrail_count")
    private Integer newContrailCount;
    @JsonProperty("frame_ref")
    private String frameRef;
    @JsonProperty("mask_png_b64")
    private String maskPngB64;
}
