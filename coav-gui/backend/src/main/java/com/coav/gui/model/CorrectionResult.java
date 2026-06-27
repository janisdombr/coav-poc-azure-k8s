package com.coav.gui.model;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class CorrectionResult {
    private String flightId;
    private String status;
    private String message;
    private String timestamp;
}
