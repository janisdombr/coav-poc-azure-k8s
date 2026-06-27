package com.coav.gui.service;

import com.coav.gui.model.Flight;
import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Profile;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.Random;

/**
 * Mock traffic generator for the MUAC upper airspace sector.
 *
 * Three flight archetypes:
 *  1. Transit  — enters from sector boundary, crosses, exits and disappears.
 *                After a gap a new aircraft with a different callsign flies the
 *                same route corridor.  Callsigns cycle through an airline pool.
 *  2. Holding  — orbits a VOR/fix indefinitely with the SAME callsign (real
 *                holding stacks don't change identity mid-hold).
 *  3. Departure — climbs out of Maastricht (EHBK), reaches cruise and exits
 *                sector to the north; disappears.  Does NOT repeat.
 */
@Service
@Profile("mock")
@RequiredArgsConstructor
public class FlightSimulatorService {

    private final FlightStateStore store;
    private final Random rng = new Random();
    private long tick = 0;

    // ── Transit corridors (MUAC upper-airspace airways) ───────────────────────
    // Each row: {startLat, startLon, endLat, endLon}
    private static final double[][] ROUTES = {
        {50.20, 3.80,  52.80, 9.00},  // SW→NE  A7 / N871  Paris → Hamburg
        {51.50, 9.20,  50.70, 3.40},  // E→W    T180       Frankfurt → Brussels
        {49.80, 6.50,  52.90, 3.20},  // SE→NW  B317       Luxembourg → North Sea
        {49.40, 4.60,  53.30, 6.80},  // S→N    UN852      Reims → Frisian Islands
    };

    // Ticks (2 s each) to cross the sector — roughly 25–32 min per route
    private static final int[] DURATIONS = {950, 780, 870, 820};

    // Cooldown ticks before the next aircraft spawns on the same route (4–7 min)
    private static final int COOLDOWN_BASE = 130;
    private static final int COOLDOWN_VAR  = 60;

    // Typical cruise FL and speed per corridor
    private static final int[] ALTITUDES = {35000, 37000, 33000, 36000};
    private static final int[] SPEEDS    = {475, 465, 480, 460};

    // Airline pools per corridor — cycle through on each new transit
    private static final String[][] ROUTE_AIRLINES = {
        {"BAW", "EZY", "VLG", "IBE", "TAP"},  // SW→NE: London–continent operators
        {"DLH", "AUA", "SWR", "BER", "WZZ"},  // E→W:   German/Austrian carriers
        {"KLM", "TRA", "DAT", "VLR", "DEN"},  // SE→NW: Benelux northbound
        {"AFR", "TVF", "HOP", "XLR", "LFR"},  // S→N:   French carriers north
    };
    private static final int[][] ROUTE_NUMBERS = {
        {214, 316, 429, 551, 682},
        {437, 593, 712, 821, 934},
        {871, 992, 104, 215, 328},
        {133, 267, 381, 475, 598},
    };

    // ── Holding stacks (fixed callsign — orbits indefinitely) ─────────────────
    // {centerLat, centerLon, radiusLat, radiusLon}
    private static final double[][] HOLDS = {
        {50.50, 4.80, 0.12, 0.19},  // Brussels  DENUT hold  (FL350)
        {52.30, 4.45, 0.10, 0.16},  // Amsterdam SUGOL hold  (FL330)
    };
    private static final int[]    HOLD_ALTS   = {35000, 33000};
    private static final int[]    HOLD_SPEEDS  = {265, 265};
    private static final String[] HOLD_IDS    = {"BEL256", "KLM892"};
    // One full orbit ≈ 420 ticks (14 min), angular step per tick:
    private static final double   HOLD_OMEGA  = 2 * Math.PI / 420.0;

    // ── Departure (EHBK → northbound, one-shot) ───────────────────────────────
    // Climbs from FL100 to FL350, then transits north-west until sector edge.
    // Total lifecycle: ~600 ticks (20 min).  No repeat — appears once on startup.
    private static final String DEP_ID       = "TUI6KL";
    private static final double DEP_START_LAT = 50.91;  // Maastricht Aachen Airport
    private static final double DEP_START_LON = 5.77;
    private static final double DEP_END_LAT   = 52.50;
    private static final double DEP_END_LON   = 4.20;
    private static final int    DEP_DURATION  = 600;

    // ── Mutable state ─────────────────────────────────────────────────────────
    private final long[]    routeProgress   = new long[ROUTES.length];
    private final boolean[] routeActive     = new boolean[ROUTES.length];
    private final long[]    routeCooldown   = new long[ROUTES.length];
    private final int[]     routeAirlineIdx = new int[ROUTES.length];
    private final String[]  routeFlightId   = new String[ROUTES.length];

    // Stagger initial progress so flights arrive spread across the sector at startup
    {
        for (int i = 0; i < ROUTES.length; i++) {
            routeProgress[i]   = (long) (DURATIONS[i] * (i + 1.0) / (ROUTES.length + 1.0));
            routeActive[i]     = true;
            routeAirlineIdx[i] = 0;
            routeFlightId[i]   = callsign(i, 0);
        }
    }

    private long depProgress = 0;
    private boolean depDone  = false;

    private String callsign(int route, int airline) {
        return ROUTE_AIRLINES[route][airline] + ROUTE_NUMBERS[route][airline];
    }

    @Scheduled(fixedRate = 2000)
    public void tick() {
        tick++;
        String iso = Instant.now().toString();

        // ── 1. Transit flights ─────────────────────────────────────────────────
        for (int i = 0; i < ROUTES.length; i++) {
            if (!routeActive[i]) {
                // Counting down gap between consecutive same-route flights
                if (--routeCooldown[i] <= 0) {
                    routeAirlineIdx[i] = (routeAirlineIdx[i] + 1) % ROUTE_AIRLINES[i].length;
                    routeFlightId[i]   = callsign(i, routeAirlineIdx[i]);
                    routeProgress[i]   = 0;
                    routeActive[i]     = true;
                }
                continue;
            }

            if (++routeProgress[i] > DURATIONS[i]) {
                // Exited the sector — stop publishing; 5-min TTL removes it from store
                routeActive[i]   = false;
                routeCooldown[i] = COOLDOWN_BASE + rng.nextInt(COOLDOWN_VAR);
                continue;
            }

            double t   = (double) routeProgress[i] / DURATIONS[i];
            double lat = ROUTES[i][0] + t * (ROUTES[i][2] - ROUTES[i][0]);
            double lon = ROUTES[i][1] + t * (ROUTES[i][3] - ROUTES[i][1]);
            int    alt = ALTITUDES[i] + (int) (Math.sin(tick * 0.003 + i) * 200);

            emit(routeFlightId[i], lat, lon, alt, SPEEDS[i], iso);
        }

        // ── 2. Holding stacks (infinite orbit, fixed callsign) ─────────────────
        for (int h = 0; h < HOLDS.length; h++) {
            double angle = tick * HOLD_OMEGA + h * Math.PI;
            double lat   = HOLDS[h][0] + HOLDS[h][2] * Math.sin(angle);
            double lon   = HOLDS[h][1] + HOLDS[h][3] * Math.cos(angle);
            int    alt   = HOLD_ALTS[h] + (int) (Math.sin(tick * 0.002 + h) * 100);
            emit(HOLD_IDS[h], lat, lon, alt, HOLD_SPEEDS[h], iso);
        }

        // ── 3. Departure (one-shot: climbs, exits, done) ──────────────────────
        if (!depDone) {
            depProgress++;
            double t = (double) depProgress / DEP_DURATION;

            double lat = DEP_START_LAT + t * (DEP_END_LAT - DEP_START_LAT);
            double lon = DEP_START_LON + t * (DEP_END_LON - DEP_START_LON);
            // Climb from FL100 to FL350, level off at cruise after 40 %
            int alt = t < 0.4
                ? (int) (10000 + t / 0.4 * 25000)
                : 35000 + (int) (Math.sin(tick * 0.003) * 100);
            int speed = t < 0.4
                ? (int) (280 + t / 0.4 * 195)  // accelerate 280 → 475 kt
                : 475;

            emit(DEP_ID, lat, lon, alt, speed, iso);

            if (depProgress >= DEP_DURATION) {
                depDone = true; // exits sector — TTL will clean up store entry
            }
        }
    }

    private void emit(String flightId, double lat, double lon, int alt, int speed, String iso) {
        boolean inIssr   = store.isInsideIssrZone(lat, lon, alt);
        boolean contrail = inIssr || rng.nextDouble() < 0.12;
        String  alert    = (contrail && inIssr) ? "CRITICAL" : contrail ? "WARNING" : null;

        store.updateFlight(Flight.builder()
            .flightId(flightId)
            .latitude(lat).longitude(lon)
            .altitudeFt(alt).speedKnots(speed)
            .contrailDetected(contrail).issrZone(inIssr)
            .alert(alert).timestamp(iso)
            .build());
    }
}
