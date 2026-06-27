package com.coav.gui.model;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class Flight {
    private String flightId;
    private double latitude;
    private double longitude;
    private int altitudeFt;
    private int speedKnots;
    private boolean contrailDetected;
    private boolean issrZone;
    private String alert; // null | "WARNING" | "CRITICAL"
    private String timestamp;
}
