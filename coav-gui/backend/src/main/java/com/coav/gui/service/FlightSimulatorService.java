package com.coav.gui.service;

import com.coav.gui.model.Flight;
import com.coav.gui.model.IssrZone;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.annotation.Profile;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Random;

@Slf4j
@Service
@Profile("mock")
@RequiredArgsConstructor
public class FlightSimulatorService {

    private final FlightStateStore store;
    private final Random rng = new Random();
    private long tick = 0;

    private List<RouteConfig> activeRoutes = new ArrayList<>();
    private List<HoldConfig> activeHolds = new ArrayList<>();
    private long lastZoneCheckTick = -999;

    private static final int COOLDOWN_BASE = 130;
    private static final int COOLDOWN_VAR = 60;

    private static class RouteConfig {
        double startLat, startLon, endLat, endLon;
        int duration, altitude, speed;
        double heading;
        String[] airlines;
        int[] numbers;

        long progress;
        boolean active;
        long cooldown;
        int airlineIdx;
        String flightId;
    }

    private static class HoldConfig {
        double lat, lon, rLat, rLon;
        int altitude, speed;
        String flightId;
    }

    private static final String DEP_ID = "TUI6KL";
    private static final String ARR_ID = "RYR912";
    private long depProgress = 0;
    private boolean depDone = false;
    private long ARR_DURATION = 600;
    private long depDuration = 600;
    private long arrProgress = ARR_DURATION / 4;
    private boolean arrDone = false;

    @Scheduled(fixedRate = 2000)
    public void tick() {
        tick++;
        String iso = Instant.now().toString();

        if (tick - lastZoneCheckTick > 450 || activeRoutes.isEmpty()) {
            recalculateDynamicScenarios();
            lastZoneCheckTick = tick;
        }

        for (RouteConfig r : activeRoutes) {
            if (!r.active) {
                if (--r.cooldown <= 0) {
                    r.airlineIdx = (r.airlineIdx + 1) % r.airlines.length;
                    r.flightId = r.airlines[r.airlineIdx] + r.numbers[r.airlineIdx];
                    r.progress = 0;
                    r.active = true;
                }
                continue;
            }

            if (++r.progress > r.duration) {
                r.active = false;
                r.cooldown = COOLDOWN_BASE + rng.nextInt(COOLDOWN_VAR);
                continue;
            }

            double t = (double) r.progress / r.duration;
            double lat = r.startLat + t * (r.endLat - r.startLat);
            double lon = r.startLon + t * (r.endLon - r.startLon);
            int alt = r.altitude + (int) (Math.sin(tick * 0.003) * 200);

            emit(r.flightId, lat, lon, alt, r.speed, r.heading, iso);
        }

        for (int h = 0; h < activeHolds.size(); h++) {
            HoldConfig hold = activeHolds.get(h);
            double omega = 2 * Math.PI / 420.0;
            double angle = tick * omega + h * Math.PI;
            double lat = hold.lat + hold.rLat * Math.sin(angle);
            double lon = hold.lon + hold.rLon * Math.cos(angle);
            int alt = hold.altitude + (int) (Math.sin(tick * 0.002 + h) * 100);

            double dLat = hold.rLat * Math.cos(angle);
            double dLon = -hold.rLon * Math.sin(angle);
            double heading = (Math.toDegrees(Math.atan2(dLon, dLat)) + 360) % 360;

            emit(hold.flightId, lat, lon, alt, hold.speed, heading, iso);
        }

        if (!depDone) {
            depProgress++;
            double t = (double) depProgress / depDuration;
            double lat = 50.91 + t * (52.50 - 50.91);
            double lon = 5.77 + t * (4.20 - 5.77);
            int alt = t < 0.4 ? (int) (10000 + t / 0.4 * 25000) : 35000;
            int speed = t < 0.4 ? (int) (280 + t / 0.4 * 195) : 475;
            emit(DEP_ID, lat, lon, alt, speed, 329.0, iso);
            if (depProgress >= depDuration)
                depDone = true;
        }

        if (!arrDone) {
            arrProgress++;
            double t = (double) arrProgress / ARR_DURATION;
            double lat = 52.50 + t * (50.91 - 52.50);
            double lon = 4.20 + t * (5.77 - 4.20);
            int alt = t < 0.6 ? 35000 : (int) (35000 * (1.0 - (t - 0.6) / 0.4));
            int speed = t < 0.6 ? 475 : 140;
            emit(ARR_ID, lat, lon, Math.max(alt, 0), Math.max(speed, 140), 165.0, iso);
            if (arrProgress >= ARR_DURATION)
                arrDone = true;
        }
    }

    /**
     * Recalculate the active flight scenarios based on the current ISSR zones. This
     * method is called periodically to update the flight paths and holding
     * patterns.
     */
    private void recalculateDynamicScenarios() {
        List<IssrZone> zones = store.getIssrZones();
        if (zones == null || zones.isEmpty()) {
            return;
        }

        activeRoutes.clear();
        activeHolds.clear();
        int n = zones.size();
        log.info("[Simulator] Rebuilding flight scenarios based on {} active ISSR zones", n);

        String[][] airlines = {
                { "DLH", "BAW", "EZY" }, { "AFR", "TVF", "KLM" }, { "AUA", "SWR", "BER" }
        };
        int[][] numbers = {
                { 437, 214, 316 }, { 133, 267, 871 }, { 593, 712, 821 }
        };

        for (int i = 0; i < 4; i++) {
            IssrZone z = zones.get(i % n);
            double cLat = (z.getMinLat() + z.getMaxLat()) / 2.0;
            double cLon = (z.getMinLon() + z.getMaxLon()) / 2.0;
            int midAlt = (z.getMinAlt() + z.getMaxAlt()) / 2;

            RouteConfig r = new RouteConfig();
            if (i % 2 == 0) {
                r.startLat = cLat + 0.4;
                r.startLon = z.getMaxLon() + 2.0;
                r.endLat = cLat - 0.4;
                r.endLon = z.getMinLon() - 2.0;
            } else {
                r.startLat = z.getMinLat() - 2.0;
                r.startLon = cLon + 0.2;
                r.endLat = z.getMaxLat() + 2.0;
                r.endLon = cLon - 0.2;
            }
            r.altitude = midAlt;
            r.speed = 470;
            r.duration = 800;
            r.heading = 45.0; // Упрощенно
            r.airlines = airlines[i % airlines.length];
            r.numbers = numbers[i % numbers.length];
            r.airlineIdx = 0;
            r.flightId = r.airlines[0] + r.numbers[0];
            r.progress = (long) (r.duration * (i + 1.0) / 5.0);
            r.active = true;

            activeRoutes.add(r);
        }

        for (int h = 0; h < Math.min(2, n); h++) {
            IssrZone z = zones.get(h);
            HoldConfig hold = new HoldConfig();
            hold.lat = (z.getMinLat() + z.getMaxLat()) / 2.0;
            hold.lon = (z.getMinLon() + z.getMaxLon()) / 2.0;
            hold.rLat = 0.12;
            hold.rLon = 0.18;
            hold.altitude = z.getMinAlt();
            hold.speed = 265;
            hold.flightId = h == 0 ? "BEL256" : "KLM892";
            activeHolds.add(hold);
        }
    }

    private void emit(String flightId, double lat, double lon, int alt, int speed,
            double heading, String iso) {
        boolean inIssr = store.isInsideIssrZone(lat, lon, alt);
        boolean contrail = inIssr || rng.nextDouble() < 0.12;

        store.updateFlight(Flight.builder()
                .flightId(flightId)
                .latitude(lat).longitude(lon)
                .altitudeFt(alt).speedKnots(speed)
                .heading(heading)
                .contrailDetected(contrail).issrZone(inIssr)
                .timestamp(iso)
                .build());
    }
}