package com.coav.gui.model;

import lombok.Builder;
import lombok.Value;

/**
 * Latest contrail-verification state of one ground camera, built from
 * EDGE_VISION_AI events. Camera-keyed: intentionally carries no flight_id —
 * contrail-to-flight attribution is out of scope for P1 (planned as P2).
 */
@Value
@Builder
public class CameraVerification {
    String  cameraId;
    String  timestamp;
    boolean contrailDetected;
    Double  confidence;
    Double  contrailPixelRatio;
    Integer contrailCount;
    Integer newContrailCount;
    String  frameRef;
    // Downscaled (<=256px) PNG segmentation mask, base64-encoded
    String  maskPngB64;
}
