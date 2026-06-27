package com.coav.gui.model;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class IssrZone {
    private String id;
    private String label;
    private double minLat;
    private double maxLat;
    private double minLon;
    private double maxLon;
    private int minAlt;
    private int maxAlt;
    private String severity;
}
