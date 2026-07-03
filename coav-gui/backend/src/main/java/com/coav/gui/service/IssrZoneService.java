package com.coav.gui.service;

import com.coav.gui.model.IssrZone;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static java.util.stream.Collectors.joining;

/**
 * Refreshes ISSR zones every 30 minutes from Open-Meteo free API (no key required).
 *
 * Physics: Open-Meteo returns RH over water (RHw). ISSR requires RH over ice (RHi).
 * Conversion: RHi = RHw × (e_sat_water(T) / e_sat_ice(T)) — Murphy & Koop 2005.
 * ISSR when RHi > 100% at cruise pressure levels (250 hPa ≈ FL340, 300 hPa ≈ FL300).
 *
 * Forecast offset: uses +5 h ahead (pre-tactical horizon).  ATC decisions for
 * cruise-level avoidance need ~4–6 h lead time; checking only current conditions
 * misses ISSR that flights will encounter later in their cruise phase.
 * In production this would use ECMWF IFS; Open-Meteo is a free proxy for the PoC.
 *
 * Falls back to FlightStateStore.FALLBACK_ZONES when API is unreachable or returns
 * no ISSR conditions.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class IssrZoneService {

    private final FlightStateStore store;
    private final ObjectMapper objectMapper;

    // MUAC region bounding box — wider than hardcoded zones to catch emerging ISSR
    private static final double LAT_MIN = 49.5, LAT_MAX = 53.5;
    private static final double LON_MIN = 2.0,  LON_MAX = 10.0;
    private static final int    GRID_LAT = 6,   GRID_LON = 8;

    private record PressureLevel(String name, int altFt) {}
    private static final List<PressureLevel> LEVELS = List.of(
        new PressureLevel("250hPa", 34_000),
        new PressureLevel("300hPa", 30_000)
    );

    private static final double RHI_THRESHOLD    = 100.0;
    private static final int    MIN_CLUSTER_SIZE = 2;
    // Pre-tactical planning horizon: ISSR zones 5 h ahead (index into hourly[] array)
    private static final int    FORECAST_HOUR    = 5;

    private final HttpClient http = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(10))
        .build();

    // Start after 60 s so the app is fully up; refresh every 30 min thereafter
    @Scheduled(fixedDelay = 30 * 60 * 1000, initialDelay = 60_000)
    public void refreshIssrZones() {
        log.info("[ISSR] Refreshing zones from Open-Meteo...");
        try {
            List<GridPoint> grid = computeGrid();
            List<IssrZone> zones = clusterToZones(grid);
            if (zones.isEmpty()) {
                log.info("[ISSR] No ISSR conditions detected — fallback zones remain active");
            } else {
                store.updateIssrZones(zones);
                log.info("[ISSR] Updated {} dynamic zone(s): {}", zones.size(),
                    zones.stream().map(IssrZone::getId).collect(joining(", ")));
            }
        } catch (Exception e) {
            log.warn("[ISSR] Refresh failed — fallback zones remain active: {}", e.getMessage());
        }
    }

    // ── Grid ──────────────────────────────────────────────────────────────────────

    private List<GridPoint> computeGrid() {
        double latStep = (LAT_MAX - LAT_MIN) / (GRID_LAT - 1);
        double lonStep = (LON_MAX - LON_MIN) / (GRID_LON - 1);
        List<GridPoint> results = new ArrayList<>();
        for (int i = 0; i < GRID_LAT; i++) {
            double lat = LAT_MIN + i * latStep;
            for (int j = 0; j < GRID_LON; j++) {
                double lon = LON_MIN + j * lonStep;
                try {
                    fetchPoint(round2(lat), round2(lon), results);
                } catch (Exception e) {
                    log.debug("[ISSR] Skip ({},{}) : {}", lat, lon, e.getMessage());
                }
            }
        }
        return results;
    }

    private void fetchPoint(double lat, double lon, List<GridPoint> out) throws Exception {
        String fields = LEVELS.stream()
            .flatMap(l -> java.util.stream.Stream.of(
                "temperature_" + l.name(), "relative_humidity_" + l.name()))
            .collect(joining(","));
        String url = "https://api.open-meteo.com/v1/forecast"
            + "?latitude=" + lat + "&longitude=" + lon
            + "&hourly=" + fields + "&forecast_days=1";

        HttpRequest req = HttpRequest.newBuilder(URI.create(url))
            .timeout(Duration.ofSeconds(10))
            .GET().build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() != 200) {
            log.debug("[ISSR] Open-Meteo HTTP {} for ({},{})", resp.statusCode(), lat, lon);
            return;
        }

        JsonNode h = objectMapper.readTree(resp.body()).path("hourly");
        for (PressureLevel level : LEVELS) {
            double tempC = h.path("temperature_" + level.name()).path(FORECAST_HOUR).asDouble(Double.NaN);
            double rhw   = h.path("relative_humidity_" + level.name()).path(FORECAST_HOUR).asDouble(Double.NaN);
            if (Double.isNaN(tempC) || Double.isNaN(rhw)) continue;
            double rhi = rhiFromRhw(rhw, tempC);
            out.add(new GridPoint(lat, lon, level.name(), level.altFt, tempC, rhw, rhi));
        }
    }

    // ── Physics (Murphy & Koop 2005) ──────────────────────────────────────────────

    private static double eSatWater(double t) {
        return 6.1078 * Math.exp(17.27 * t / (t + 237.3));
    }

    private static double eSatIce(double t) {
        double tk = t + 273.15;
        return Math.exp(9.550426 - 5723.265 / tk + 3.53068 * Math.log(tk) - 0.00728332 * tk) / 100.0;
    }

    /** RHw → RHi conversion. Returns rhwPct unchanged for T ≥ 0°C (ice physics only below 0). */
    static double rhiFromRhw(double rhwPct, double tempC) {
        if (tempC >= 0.0 || rhwPct <= 0) return rhwPct;
        return rhwPct * eSatWater(tempC) / eSatIce(tempC);
    }

    // ── Clustering ────────────────────────────────────────────────────────────────

    private List<IssrZone> clusterToZones(List<GridPoint> grid) {
        List<GridPoint> issr = grid.stream().filter(p -> p.rhi() > RHI_THRESHOLD).toList();
        if (issr.isEmpty()) return List.of();

        double latStep  = (LAT_MAX - LAT_MIN) / (GRID_LAT - 1);
        double lonStep  = (LON_MAX - LON_MIN) / (GRID_LON - 1);
        double proximity = Math.max(latStep, lonStep) * 1.5;

        // Group by pressure level, then flood-fill connected components
        Map<String, List<GridPoint>> byLevel = new HashMap<>();
        for (GridPoint p : issr) byLevel.computeIfAbsent(p.level(), k -> new ArrayList<>()).add(p);

        List<IssrZone> zones = new ArrayList<>();
        int zoneIdx = 0;

        for (List<GridPoint> pts : byLevel.values()) {
            List<GridPoint> remaining = new ArrayList<>(pts);
            while (!remaining.isEmpty()) {
                List<GridPoint> cluster = new ArrayList<>();
                cluster.add(remaining.remove(0));
                boolean changed = true;
                while (changed) {
                    changed = false;
                    List<GridPoint> next = new ArrayList<>();
                    for (GridPoint p : remaining) {
                        boolean near = cluster.stream().anyMatch(c ->
                            Math.abs(p.lat() - c.lat()) <= proximity &&
                            Math.abs(p.lon() - c.lon()) <= proximity);
                        if (near) { cluster.add(p); changed = true; }
                        else next.add(p);
                    }
                    remaining = next;
                }
                if (cluster.size() < MIN_CLUSTER_SIZE) continue;

                zoneIdx++;
                int altFt    = cluster.get(0).altFt();
                double maxRhi = cluster.stream().mapToDouble(GridPoint::rhi).max().orElse(0);
                double minLat = cluster.stream().mapToDouble(GridPoint::lat).min().orElse(0);
                double maxLat = cluster.stream().mapToDouble(GridPoint::lat).max().orElse(0);
                double minLon = cluster.stream().mapToDouble(GridPoint::lon).min().orElse(0);
                double maxLon = cluster.stream().mapToDouble(GridPoint::lon).max().orElse(0);
                char   letter = (char) ('A' + zoneIdx - 1);

                zones.add(IssrZone.builder()
                    .id("Dynamic-" + letter)
                    .label(String.format("Dynamic Zone %c (RHi %.0f%%)", letter, maxRhi))
                    .minLat(round2(minLat - latStep / 2))
                    .maxLat(round2(maxLat + latStep / 2))
                    .minLon(round2(minLon - lonStep / 2))
                    .maxLon(round2(maxLon + lonStep / 2))
                    .minAlt(altFt - 2_000)
                    .maxAlt(altFt + 2_000)
                    .severity("CRITICAL")
                    .build());
            }
        }
        return zones;
    }

    private static double round2(double v) { return Math.round(v * 100.0) / 100.0; }

    private record GridPoint(double lat, double lon, String level, int altFt,
                             double tempC, double rhw, double rhi) {}
}
