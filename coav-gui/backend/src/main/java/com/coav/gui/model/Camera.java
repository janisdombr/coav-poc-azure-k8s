package com.coav.gui.model;

/**
 * Ground all-sky camera position. FOV = looking up; a flight is "in view"
 * when its elevation angle from the camera is >= elevationCutoffDeg.
 * FOV intersection is computed on the frontend — no camera->flight link here.
 */
public record Camera(String id, double lat, double lon, double elevationCutoffDeg) {}
