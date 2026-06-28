package com.coav.gui.model;

import lombok.Builder;
import lombok.Data;

@Data
@Builder(toBuilder = true)
public class Advisory {
    private String id;
    private String flightId;
    private String zoneId;
    private String text;
    private int currentFl;
    private int recommendedFlUp;    // climb option, e.g. FL370
    private int recommendedFlDown;  // descend option, e.g. FL330
    private int estimatedMinutes;
    private String status;          // "PENDING" | "ACCEPTED" | "REJECTED"
    private String generatedAt;
    private String decidedAt;       // null until FDO acts
}
