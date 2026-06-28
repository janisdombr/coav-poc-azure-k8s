package com.coav.gui.model;

import lombok.Builder;
import lombok.Data;

@Data
@Builder(toBuilder = true)
public class Flight {
    private String flightId;
    private double latitude;
    private double longitude;
    private int altitudeFt;
    private int speedKnots;
    private double heading;            // degrees 0=N 90=E 180=S 270=W
    private boolean contrailDetected;
    private boolean issrZone;
    private String alert;              // null | "WARNING" | "CRITICAL" | "APPROACHING"
    private String approachingZoneId;  // set when alert = "APPROACHING"
    private Integer approachingMinutes;
    private String timestamp;
}
