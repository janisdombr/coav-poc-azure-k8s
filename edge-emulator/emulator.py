import base64
import threading
import time
import datetime
import os
import sys
import math
import random
import json as json_lib
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field, ValidationError
from azure.eventhub import EventHubProducerClient, EventData

# OpenCV/NumPy power the camera verification channel (listed in requirements.txt).
# The ADS-B channel must keep running even in a minimal environment without them,
# so the import is tolerant — CameraProducer disables itself if they are missing.
try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover — CI installs requirements.txt
    cv2 = None
    np = None

# ── Telemetry schemas (OWASP A03:2021 — validation before sending) ─────────────

class ADSBTelemetry(BaseModel):
    """Flight-keyed ADS-B position message."""
    message_type: Literal["ADSB_TELEMETRY"]
    flight_id: str = Field(..., min_length=3, max_length=12, pattern=r"^[A-Z0-9\-]+$")
    timestamp: str
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    altitude_ft: int = Field(..., ge=0, le=60000)
    speed_knots: int = Field(..., ge=0, le=1000)
    heading: float | None = Field(None, ge=0.0, le=360.0)


class EdgeVisionAI(BaseModel):
    """
    Camera-keyed ground-camera verification message (Day 11 / P1).

    Deliberately carries NO flight_id — the camera channel is an independent
    verification feed (decoupled, like MUAC slide 17). Camera→flight attribution
    is out of scope (P2); flight alerts are pure ISSR geometry on the backend.
    """
    message_type: Literal["EDGE_VISION_AI"]
    camera_id: str = Field(..., min_length=3, max_length=20, pattern=r"^[A-Z][A-Z0-9\-]+$")
    timestamp: str
    contrail_detected: bool
    confidence: float = Field(..., ge=0.0, le=1.0)
    contrail_pixel_ratio: float = Field(..., ge=0.0, le=1.0)
    contrail_count: int = Field(..., ge=0, le=500)
    new_contrail_count: int = Field(..., ge=0, le=500)
    frame_ref: str = Field(..., min_length=3, max_length=64, pattern=r"^[a-z0-9_\-]+$")
    # base64 PNG of the segmentation mask, downscaled to ≤256 px (bounded payload)
    mask_png_b64: str | None = Field(None, max_length=120_000)


# Dispatch table for outbound validation — one model per channel
MODEL_BY_TYPE: dict[str, type[BaseModel]] = {
    "ADSB_TELEMETRY": ADSBTelemetry,
    "EDGE_VISION_AI": EdgeVisionAI,
}


# ── ISSR zone management — single source of truth from backend API ─────────────

BACKEND_URL     = os.getenv("BACKEND_URL", "http://localhost:8080")
ZONE_REFRESH_S  = 30 * 60   # normal re-fetch cadence once on dynamic zones (matches IssrZoneService)
FALLBACK_POLL_S = 60        # tighter re-fetch cadence while still on Alpha/Bravo fallback —
                             # IssrZoneService typically publishes dynamic zones ~60s after backend start
TICK_S          = 3          # seconds per simulation tick

# ── Health endpoint (Option A: readiness by DATA, not liveness) ────────────────
# ACI only knows "container is Running" — it has no idea whether the emulator is
# actually still producing telemetry. This tiny /health endpoint reports 200 only
# if a batch was successfully sent recently; 503 otherwise. Wired to an ACI
# liveness_probe (terraform/app/build.tf) so a stuck-but-running emulator gets
# restarted automatically.
HEALTH_PORT       = 8081
HEALTH_FRESH_S     = 15   # must have sent within this many seconds to be considered healthy
LAST_SEND_TS       = 0.0  # module-level, updated right after producer.send_batch() succeeds

# Maastricht Aachen Airport (EHBK) — real location of MUAC contrail cameras
MAASTRICHT_LAT = 50.911
MAASTRICHT_LON = 5.770

# Used only if API is unreachable at startup
FALLBACK_ZONES: list[dict] = [
    {"id": "ALPHA", "minLat": 50.20, "maxLat": 51.00,
     "minLon": 3.80, "maxLon": 5.40, "minAlt": 33000, "maxAlt": 38000},
    {"id": "BRAVO", "minLat": 51.30, "maxLat": 52.50,
     "minLon": 5.80, "maxLon": 8.20, "minAlt": 31000, "maxAlt": 37000},
]


class _HealthHandler(BaseHTTPRequestHandler):
    """
    GET /health → 200 if a batch was sent within HEALTH_FRESH_S seconds, else 503.
    This is readiness-by-data, not liveness — a hung-but-running process (e.g.
    stuck on an Event Hub call) will start returning 503 and the ACI liveness_probe
    (terraform/app/build.tf) will restart the container.
    """

    def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler API
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return
        age = time.time() - LAST_SEND_TS
        ok = age < HEALTH_FRESH_S
        body = json_lib.dumps({
            "ok": ok,
            "last_send_age_s": round(age, 1),
            "tick": tick,
        }).encode()
        self.send_response(200 if ok else 503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # noqa: A003 — silence default access log
        pass


def start_health_server(port: int = HEALTH_PORT) -> HTTPServer | None:
    """
    Starts the /health HTTP server on a daemon thread. Never raises — if the
    port is unavailable (e.g. already bound in a test), the emulator logs and
    keeps running without a health endpoint rather than crashing the ADS-B loop.
    Must be called from main(), NOT at import time — tests import this module
    and must not have a socket opened as a side effect.
    """
    try:
        server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    except OSError as exc:
        print(f"[Emulator] Could not start /health server on port {port}: {exc}")
        return None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[Emulator] /health server listening on :{port}")
    return server


def _zone_signature(zones: list[dict]) -> tuple:
    """
    Geometry fingerprint of the zone set. Used to decide whether routes must be
    recomputed: reinit only fires when the geometry actually changed, not on every
    30-min refresh that returns the same zones.
    """
    return tuple(sorted(
        (z.get("id"), round(z.get("minLat", 0), 2), round(z.get("maxLat", 0), 2),
         round(z.get("minLon", 0), 2), round(z.get("maxLon", 0), 2),
         z.get("minAlt"), z.get("maxAlt"))
        for z in zones
    ))


def fetch_issr_zones(retries: int = 3, delay: int = 5) -> list[dict]:
    """Fetch current ISSR zones from backend REST API with retry."""
    url = f"{BACKEND_URL}/api/issr-zones"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=8) as resp:
                data = json_lib.loads(resp.read().decode())
            if data:
                print(f"[Emulator] Fetched {len(data)} zone(s): "
                      f"{[z['id'] for z in data]}")
                return data
            print("[Emulator] API returned empty zone list")
        except Exception as exc:
            print(f"[Emulator] Zone fetch attempt {attempt + 1}/{retries}: {exc}")
            if attempt < retries - 1:
                time.sleep(delay)
    print("[Emulator] Using fallback zones (Alpha/Bravo)")
    return list(FALLBACK_ZONES)


def wait_for_dynamic_zones() -> list[dict]:
    """
    UNUSED by main() as of Option A (non-blocking start) — kept for reference /
    manual debugging only. main() now uses a single fetch_issr_zones() call and
    an adaptive re-poll in the send loop (FALLBACK_POLL_S while on fallback,
    ZONE_REFRESH_S once dynamic) instead of blocking up to 15 min here before
    the first telemetry is sent.

    Poll backend until IssrZoneService has replaced the Alpha/Bravo startup
    fallback with real Open-Meteo zones (initial delay ≈ 60 s in Java).
    Also handles ACI cold-start where backend is not yet reachable.
    Max wait: 15 min (90 × 10 s).  Falls back to FALLBACK_ZONES on timeout.
    """
    fallback_ids = {"ALPHA", "BRAVO"}
    url = f"{BACKEND_URL}/api/issr-zones"
    print("[Emulator] Waiting for dynamic ISSR zones from IssrZoneService …")
    for attempt in range(90):
        try:
            with urllib.request.urlopen(url, timeout=8) as resp:
                data = json_lib.loads(resp.read().decode())
            if data:
                zone_ids = {z["id"] for z in data}
                if not zone_ids.issubset(fallback_ids):
                    print(f"[Emulator] Dynamic zones ready after {attempt * 10}s: "
                          f"{sorted(zone_ids)}")
                    return data
                if attempt % 6 == 0:
                    print(f"[Emulator] Still fallback {sorted(zone_ids)} — "
                          f"IssrZoneService not ready yet, elapsed {attempt * 10}s …")
        except Exception as exc:
            if attempt % 6 == 0:
                print(f"[Emulator] Backend not reachable (attempt {attempt + 1}/90): {exc}")
        time.sleep(10)
    print("[Emulator] Zone-wait timeout — using Alpha/Bravo fallback")
    return list(FALLBACK_ZONES)


# NOTE (Day 11 / P1): the flight-keyed contrail helpers (is_inside_zone /
# is_contrail_detectable) were removed. Flight alerts are now derived from pure
# ISSR geometry on the backend; the emulator no longer fabricates a per-flight
# contrail flag. Camera detections live in CameraProducer (camera-keyed).


# ── Geography helper ──────────────────────────────────────────────────────────

def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """True bearing in degrees (0=N 90=E) from A to B."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = (math.cos(lat1) * math.sin(lat2)
         - math.sin(lat1) * math.cos(lat2) * math.cos(dlon))
    return (math.degrees(math.atan2(x, y)) + 360) % 360


# ── Route generator — all alert states guaranteed ─────────────────────────────

def compute_simulation(zones: list[dict]) -> dict:
    """
    Derive simulation parameters PER ZONE — not from one merged bounding box —
    so that geographically separated zones (e.g. a northern + a southern
    dynamic ISSR zone from IssrZoneService/Open-Meteo) each get their own
    holds and transit traffic. A shared-bbox center/BUF can fall in the GAP
    between two distant zones and leave BOTH zones without any hold/transit
    passing through them (bug found by simulation: 0% CRITICAL, ~9% APPROACHING
    for a north/south zone split — every route/hold missed both zones).

      CRITICAL    — one holding stack orbits inside EVERY zone (round-robin:
                    hold h → zones[h % N] — guarantees a hold per zone)
      APPROACHING — each transit route enters ITS OWN assigned zone from
                    outside (BUF computed against THAT zone's bbox, not a
                    global one). Routes are assigned zones round-robin
                    (route i → zones[i % N]), so with N=2 zones get 2 routes
                    each; with N=1 all 4 routes/both holds use that one zone
                    (identical to the pre-fix single-zone behaviour).
      null        — transit routes after they exit their zone's far side, and
                    route 3 (the "above ceiling" pattern) which flies above
                    ITS OWN assigned zone's ceiling — never enters by
                    altitude, regardless of which zone it geometrically sits
                    over.

    Alerts are geometry-only (P1): contrail detection no longer drives alert
    state — that is the decoupled camera verification channel.
    """
    n = len(zones)

    def zone_center(z: dict) -> tuple[float, float]:
        return (z["minLat"] + z["maxLat"]) / 2, (z["minLon"] + z["maxLon"]) / 2

    def zone_mid_alt(z: dict) -> int:
        return int((z["minAlt"] + z["maxAlt"]) / 2)   # e.g. FL340 for FL320–360

    # Approach buffer: 2.2° guarantees > 8 min APPROACHING phase before zone entry
    BUF = 2.2

    # (startLat, startLon, endLat, endLon) per route, each built from ITS OWN
    # assigned zone — stagger initial progress so all four phases
    # (outside → APPROACHING → CRITICAL → exited) are visible from the first
    # tick. Round-robin zone assignment (i % n) is what fixes the "gap
    # between distant zones" bug.
    routes: list[tuple] = []
    altitudes: list[int] = []
    speeds = [460, 450, 475, 465]

    for i in range(4):
        z = zones[i % n]
        z_clat, z_clon = zone_center(z)
        z_mid_alt = zone_mid_alt(z)

        if i % 4 == 0:
            # East → West at zone cruise alt  [APPROACHING then CRITICAL then null]
            routes.append((round(z_clat + 0.4, 2), round(z["maxLon"] + BUF, 2),
                            round(z_clat - 0.4, 2), round(z["minLon"] - 1.5, 2)))
            altitudes.append(z_mid_alt)
        elif i % 4 == 1:
            # South → North at zone cruise alt [APPROACHING then CRITICAL then null]
            routes.append((round(z["minLat"] - BUF, 2), round(z_clon + 0.2, 2),
                            round(z["maxLat"] + 1.5, 2), round(z_clon - 0.2, 2)))
            altitudes.append(z_mid_alt)
        elif i % 4 == 2:
            # North-East → South-West          [APPROACHING then CRITICAL then null]
            routes.append((round(z["maxLat"] + 1.2, 2), round(z["maxLon"] + 1.2, 2),
                            round(z["minLat"] - 1.0, 2), round(z["minLon"] - 1.0, 2)))
            altitudes.append(z_mid_alt + 1000)
        else:
            # East → West ABOVE this zone's ceiling — never enters (altitude
            # clearance is relative to the assigned zone's OWN ceiling, so it
            # stays a reliable "null" route no matter which zone it sits over)
            routes.append((round(z_clat + 1.2, 2), round(z["maxLon"] + 2.5, 2),
                            round(z_clat - 1.2, 2), round(z["minLon"] - 1.5, 2)))
            altitudes.append(z["maxAlt"] + 3000)

    headings = [_bearing(*r) for r in routes]

    def route_ticks(i: int) -> int:
        s_lat, s_lon, e_lat, e_lon = routes[i]
        dlat = abs(e_lat - s_lat) * 60                                    # nm
        dlon = abs(e_lon - s_lon) * 60 * math.cos(math.radians((s_lat + e_lat) / 2))
        dist = math.sqrt(dlat**2 + dlon**2)
        return max(300, int(dist / speeds[i] * 3600 / TICK_S))

    durations = [route_ticks(i) for i in range(len(routes))]

    airlines = [
        ["DLH", "BAW", "EZY", "IBE", "TAP"],   # E→W
        ["AFR", "TVF", "KLM", "DAT", "VLG"],   # S→N
        ["AUA", "SWR", "BER", "VLR", "DEN"],   # NE→SW
        ["WZZ", "HOP", "XLR", "TRA", "LFR"],   # Above zone (no alert)
    ]
    numbers = [
        [437, 214, 316, 551, 682],
        [133, 267, 871, 104, 429],
        [593, 712, 821, 215, 328],
        [934, 381, 475, 992, 598],
    ]

    # Holding stacks — round-robin one orbit per zone → always CRITICAL in
    # EVERY zone, even when zones are geographically separated. With N=1 both
    # holds land in the same (only) zone, at their usual two distinct offsets
    # — identical to the pre-fix behaviour.
    HOLD_OFFSETS = [(-0.4, -0.5, 0.12, 0.18), (0.5, 0.5, 0.10, 0.15)]
    holds: list[tuple] = []
    hold_alts: list[int] = []
    for h in range(2):
        z = zones[h % n]
        z_clat, z_clon = zone_center(z)
        dlat, dlon, r_lat, r_lon = HOLD_OFFSETS[h]
        holds.append((round(z_clat + dlat, 2), round(z_clon + dlon, 2), r_lat, r_lon))
        hold_alts.append(zone_mid_alt(z) - (0 if h == 0 else 1000))

    # Departure/arrival target the zone geographically NEAREST to Maastricht
    # (nm-scaled distance, not a global bbox) so a far-away zone doesn't pull
    # the climb/descent profile toward a zone Maastricht traffic would never
    # actually route through.
    def _nm_dist_to_maastricht(z: dict) -> float:
        c_lat, c_lon = zone_center(z)
        dlat_nm = (MAASTRICHT_LAT - c_lat) * 60
        dlon_nm = (MAASTRICHT_LON - c_lon) * 60 * math.cos(
            math.radians((MAASTRICHT_LAT + c_lat) / 2))
        return math.hypot(dlat_nm, dlon_nm)

    near = min(zones, key=_nm_dist_to_maastricht)
    near_clat, near_clon = zone_center(near)
    near_xl = near["maxLat"]
    mid_alt = zone_mid_alt(near)   # dep/arr cruise altitude reference

    # Departure: climbs from Maastricht Aachen Airport (EHBK) into the nearest zone
    dep_start = (MAASTRICHT_LAT, MAASTRICHT_LON)
    dep_end   = (round(near_xl + 0.5, 2), round(near_clon + 0.3, 2))
    dep_hdg   = _bearing(dep_start[0], dep_start[1], dep_end[0], dep_end[1])

    # Arrival: descends from the nearest zone to Maastricht Aachen Airport (EHBK)
    arr_start = (round(near_xl + 0.5, 2), round(near_clon - 0.2, 2))
    arr_end   = (MAASTRICHT_LAT, MAASTRICHT_LON)
    arr_hdg   = _bearing(arr_start[0], arr_start[1], arr_end[0], arr_end[1])

    return dict(
        routes=routes, altitudes=altitudes, speeds=speeds,
        headings=headings, durations=durations,
        airlines=airlines, numbers=numbers,
        holds=holds, hold_alts=hold_alts,
        dep_start=dep_start, dep_end=dep_end, dep_heading=dep_hdg,
        arr_start=arr_start, arr_end=arr_end, arr_heading=arr_hdg,
        mid_alt=mid_alt,
    )


# ── Mutable simulation state — initialised after zone fetch ───────────────────

ROUTES:         list[tuple] = []
ALTITUDES:      list[int]   = []
SPEEDS:         list[int]   = []
ROUTE_HEADINGS: list[float] = []
DURATIONS:      list[int]   = []
ROUTE_AIRLINES: list[list]  = []
ROUTE_NUMBERS:  list[list]  = []
HOLDS:          list[tuple] = []
HOLD_ALTS:      list[int]   = []
DEP_START       = (0.0, 0.0)
DEP_END         = (0.0, 0.0)
DEP_HEADING     = 0.0
ARR_START       = (0.0, 0.0)
ARR_END         = (0.0, 0.0)
ARR_HEADING     = 0.0
CRUISE_ALT      = 0

HOLD_IDS    = ["BEL256", "KLM892"]
HOLD_SPEEDS = [265, 265]
HOLD_OMEGA  = 2 * math.pi / 420.0   # one full orbit ≈ 420 ticks (21 min)
DEP_ID       = "TUI6KL"   # TUI fly Belgium — Maastricht departure
ARR_ID       = "RYR912"   # Ryanair — Maastricht arrival
DEP_DURATION = 600
ARR_DURATION = 600
COOLDOWN_BASE = 130
COOLDOWN_VAR  = 60

route_progress:    list[int]  = []
route_active:      list[bool] = []
route_cooldown:    list[int]  = []
route_airline_idx: list[int]  = []
route_flight_id:   list[str]  = []
dep_progress = 0
dep_done     = False
arr_progress = 0
arr_done     = False
tick         = 0
zones_cache: list[dict] = []
last_zone_refresh = 0.0


def make_callsign(route_idx: int, airline_idx: int) -> str:
    return ROUTE_AIRLINES[route_idx][airline_idx] + str(ROUTE_NUMBERS[route_idx][airline_idx])


def init_simulation(zones: list[dict]) -> None:
    """Initialise all route/hold/dep/arr state from zone geometry."""
    global ROUTES, ALTITUDES, SPEEDS, ROUTE_HEADINGS, DURATIONS
    global ROUTE_AIRLINES, ROUTE_NUMBERS, HOLDS, HOLD_ALTS
    global DEP_START, DEP_END, DEP_HEADING
    global ARR_START, ARR_END, ARR_HEADING, CRUISE_ALT
    global route_progress, route_active, route_cooldown
    global route_airline_idx, route_flight_id
    global dep_progress, dep_done, arr_progress, arr_done

    cfg = compute_simulation(zones)
    ROUTES         = cfg["routes"]
    ALTITUDES      = cfg["altitudes"]
    SPEEDS         = cfg["speeds"]
    ROUTE_HEADINGS = cfg["headings"]
    DURATIONS      = cfg["durations"]
    ROUTE_AIRLINES = cfg["airlines"]
    ROUTE_NUMBERS  = cfg["numbers"]
    HOLDS          = cfg["holds"]
    HOLD_ALTS      = cfg["hold_alts"]
    DEP_START      = cfg["dep_start"]
    DEP_END        = cfg["dep_end"]
    DEP_HEADING    = cfg["dep_heading"]
    ARR_START      = cfg["arr_start"]
    ARR_END        = cfg["arr_end"]
    ARR_HEADING    = cfg["arr_heading"]
    CRUISE_ALT     = cfg["mid_alt"]

    n = len(ROUTES)
    # Stagger progress so different alert states are visible from the first tick
    route_progress    = [int(DURATIONS[i] * (i + 1) / (n + 1)) for i in range(n)]
    route_active      = [True] * n
    route_cooldown    = [0] * n
    route_airline_idx = [0] * n
    route_flight_id   = [make_callsign(i, 0) for i in range(n)]
    dep_progress = 0
    dep_done     = False
    arr_progress = ARR_DURATION // 4   # stagger: arrival starts mid-descent so it's visible immediately
    arr_done     = False

    zone_ids = [z["id"] for z in zones]
    print(f"[Emulator] Zones used: {zone_ids}")
    for i, r in enumerate(ROUTES):
        print(f"  Route {i}: ({r[0]},{r[1]}) → ({r[2]},{r[3]})  "
              f"FL{ALTITUDES[i]//100}  hdg={ROUTE_HEADINGS[i]:.0f}°  "
              f"dur={DURATIONS[i]} ticks ({DURATIONS[i]*TICK_S//60} min)")
    for h in range(len(HOLDS)):
        print(f"  Hold {HOLD_IDS[h]}: center=({HOLDS[h][0]},{HOLDS[h][1]}) "
              f"FL{HOLD_ALTS[h]//100}")
    print(f"  Departure {DEP_ID}: {DEP_START} → {DEP_END}  hdg={DEP_HEADING:.0f}°")
    print(f"  Arrival   {ARR_ID}: {ARR_START} → {ARR_END}  hdg={ARR_HEADING:.0f}°")


# ── Tick function ─────────────────────────────────────────────────────────────

def build_payloads() -> list[dict]:
    global tick, dep_progress, dep_done, arr_progress, arr_done
    global route_progress, route_active, route_cooldown, route_airline_idx, route_flight_id

    tick += 1
    iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    active: list[tuple] = []   # (fid, lat, lon, alt, spd, hdg)

    # ── 1. Transit flights ─────────────────────────────────────────────────────
    for i in range(len(ROUTES)):
        if not route_active[i]:
            route_cooldown[i] -= 1
            if route_cooldown[i] <= 0:
                route_airline_idx[i] = (route_airline_idx[i] + 1) % len(ROUTE_AIRLINES[i])
                route_flight_id[i]   = make_callsign(i, route_airline_idx[i])
                route_progress[i]    = 0
                route_active[i]      = True
            continue
        route_progress[i] += 1
        if route_progress[i] > DURATIONS[i]:
            route_active[i]   = False
            route_cooldown[i] = COOLDOWN_BASE + random.randint(0, COOLDOWN_VAR)
            continue
        t   = route_progress[i] / DURATIONS[i]
        s_lat, s_lon, e_lat, e_lon = ROUTES[i]
        lat = s_lat + t * (e_lat - s_lat)
        lon = s_lon + t * (e_lon - s_lon)
        alt = ALTITUDES[i] + int(math.sin(tick * 0.003 + i) * 200)
        active.append((route_flight_id[i], lat, lon, alt, SPEEDS[i], ROUTE_HEADINGS[i]))

    # ── 2. Holding stacks (fixed callsign, endless orbit) ─────────────────────
    for h in range(len(HOLDS)):
        angle = tick * HOLD_OMEGA + h * math.pi
        lat   = HOLDS[h][0] + HOLDS[h][2] * math.sin(angle)
        lon   = HOLDS[h][1] + HOLDS[h][3] * math.cos(angle)
        alt   = HOLD_ALTS[h] + int(math.sin(tick * 0.002 + h) * 100)
        r_lat, r_lon = HOLDS[h][2], HOLDS[h][3]
        hdg   = (math.degrees(math.atan2(
            -r_lon * math.sin(angle), r_lat * math.cos(angle))) + 360) % 360
        active.append((HOLD_IDS[h], lat, lon, alt, HOLD_SPEEDS[h], round(hdg, 1)))

    # ── 3. Departure — TUI6KL climbs from Maastricht Aachen Airport into zone ───
    if not dep_done:
        dep_progress += 1
        t   = dep_progress / DEP_DURATION
        lat = DEP_START[0] + t * (DEP_END[0] - DEP_START[0])
        lon = DEP_START[1] + t * (DEP_END[1] - DEP_START[1])
        alt = int(10000 + t / 0.4 * 25000) if t < 0.4 \
              else CRUISE_ALT + int(math.sin(tick * 0.003) * 100)
        spd = int(280 + t / 0.4 * 195) if t < 0.4 else 475
        active.append((DEP_ID, lat, lon, min(alt, CRUISE_ALT + 200), min(spd, 475), DEP_HEADING))
        if dep_progress >= DEP_DURATION:
            dep_done = True

    # ── 4. Arrival — RYR912 descends from north of zone to Maastricht Aachen ───
    if not arr_done:
        arr_progress += 1
        t   = arr_progress / ARR_DURATION
        lat = ARR_START[0] + t * (ARR_END[0] - ARR_START[0])
        lon = ARR_START[1] + t * (ARR_END[1] - ARR_START[1])
        # cruise for first 60 %, then descend to ground
        if t < 0.6:
            alt = CRUISE_ALT + int(math.sin(tick * 0.003) * 100)
            spd = 475
        else:
            descent_frac = (t - 0.6) / 0.4   # 0 → 1 during final descent
            alt = int(CRUISE_ALT * (1.0 - descent_frac))
            spd = int(475 - descent_frac * 335)   # 475 kt → ~140 kt at landing
        active.append((ARR_ID, lat, lon, max(alt, 0), max(spd, 140), ARR_HEADING))
        if arr_progress >= ARR_DURATION:
            arr_done = True

    # ── 5. Build ADS-B events — flight-keyed channel only ─────────────────────
    # EDGE_VISION_AI is produced separately by CameraProducer (camera-keyed,
    # decoupled). Flight alerts are pure ISSR geometry on the backend — the
    # emulator never attaches a contrail flag to a specific flight.
    events: list[dict] = []
    for fid, lat, lon, alt, spd, hdg in active:
        events.append({
            "message_type": "ADSB_TELEMETRY",
            "flight_id": fid, "timestamp": iso,
            "latitude": round(lat, 5), "longitude": round(lon, 5),
            "altitude_ft": alt, "speed_knots": spd,
            "heading": round(hdg, 1),
        })
    return events


# ── Camera verification channel (Day 11 / P1) ─────────────────────────────────
#
# Independent camera-keyed channel: real U-Net segmentation (edge-pi/python/
# inference.py, weights optional) or an OpenCV heuristic fallback, running on
# held-out GVCCS *val* frames (split seed=42, identical to train.py — never
# frames the model saw in training).
#
# Caveat (also stated in UI/README): physically ONE GVCCS camera
# (Brétigny-sur-Orge), time-sliced across 4 virtual positions to illustrate
# the planned MUAC ground-camera network (techspec 3.1(3)).
#
# CAMERAS is a Python copy of the Java constant (coav-gui backend CameraStore)
# — keep both in sync.

CAMERAS: list[dict] = [
    {"id": "CAM-ALPHA", "lat": 50.60, "lon": 4.60, "elevation_cutoff_deg": 20.0},
    {"id": "CAM-BRAVO", "lat": 51.90, "lon": 7.00, "elevation_cutoff_deg": 20.0},
    {"id": "CAM-EHBK",  "lat": 50.92, "lon": 5.77, "elevation_cutoff_deg": 20.0},
    {"id": "CAM-NORTH", "lat": 52.30, "lon": 6.50, "elevation_cutoff_deg": 20.0},
]

# Held-out GVCCS val frames — generate with: python prepare_val_frames.py
FRAMES_DIR = Path(os.getenv("FRAMES_DIR",
                            str(Path(__file__).resolve().parent / "frames")))
# Location of edge-pi/python/inference.py (ContrailDetector)
INFERENCE_DIR = os.getenv(
    "INFERENCE_DIR",
    str(Path(__file__).resolve().parent.parent / "edge-pi" / "python"))

MASK_MAX_SIDE       = 256    # mask downscale for PNG payload + temporal delta
MIN_COMPONENT_PX    = 12     # ignore speckle components below this area (≤256px scale)
PIXEL_RATIO_MIN     = 0.001  # detection floor — mirrors inference.PIXEL_RATIO_THRESHOLD


class CameraProducer:
    """
    Emits one EDGE_VISION_AI message per camera per tick.

    Frame source priority:
      1. FRAMES_DIR/manifest.json — GVCCS held-out val frames (prepare_val_frames.py)
      2. Synthetic sky frames (deterministic, in-memory) — CI/demo without data

    Inference source priority (Day 11 / P1, offline-precompute variant "B"):
      1. FRAMES_DIR/precomputed.json — real U-Net results, precomputed offline
         (see precompute_inference.py) and replayed with numpy+opencv only —
         no torch/segmentation_models_pytorch needed in the cloud image.
      2. ContrailDetector from edge-pi/python/inference.py
         (itself falls back ONNX → PyTorch → OpenCV heuristic when weights absent)
      3. Built-in OpenCV heuristic (mirror of inference.py fallback) when
         inference.py is not shipped with the container
    """

    def __init__(self, frames_dir: Path | None = None,
                 cameras: list[dict] | None = None):
        self.cameras = cameras if cameras is not None else CAMERAS
        self.enabled = cv2 is not None and np is not None
        self._frames: list[dict] = []          # [{frame_ref, path|None}]
        self._synthetic: dict = {}             # frame_ref → np.ndarray
        self._from_manifest = False            # real GVCCS frames vs synthetic fallback
        self._cursor = [0] * len(self.cameras)
        self._prev_mask: dict = {c["id"]: None for c in self.cameras}
        self.detector = None
        self._precomputed: dict | None = None  # frame_ref → precomputed inference result
        self.source = "opencv"
        if not self.enabled:
            print("[Camera] OpenCV/NumPy unavailable — camera channel disabled "
                  "(ADS-B channel keeps running)")
            return
        resolved_dir = Path(frames_dir) if frames_dir else FRAMES_DIR
        self._load_frames(resolved_dir)
        if self._from_manifest:
            self._precomputed = self._load_precomputed(resolved_dir)
        if self._precomputed is not None:
            self.source = "precomputed"
        else:
            self.detector = self._init_detector()
            self.source = "live-model" if self.detector is not None else "opencv"
        print(f"[Camera] camera source = {self.source}")

    # ── Frame loading ──────────────────────────────────────────────────────────

    def _load_frames(self, frames_dir: Path) -> None:
        manifest = frames_dir / "manifest.json"
        if manifest.exists():
            try:
                with open(manifest) as f:
                    data = json_lib.load(f)
                for entry in data.get("frames", []):
                    path = frames_dir / entry["file"]
                    if path.exists():
                        self._frames.append(
                            {"frame_ref": entry["frame_ref"], "path": path})
            except (OSError, ValueError, KeyError) as exc:
                print(f"[Camera] Bad manifest {manifest}: {exc}")
        self._from_manifest = bool(self._frames)
        if self._frames:
            print(f"[Camera] {len(self._frames)} GVCCS held-out val frames "
                  f"(split seed=42, same as train.py) from {frames_dir}")
        else:
            self._frames = self._make_synthetic_frames()
            print("[Camera] No GVCCS frames found — using synthetic sky frames. "
                  "Run prepare_val_frames.py to extract the real val split.")

    def _load_precomputed(self, frames_dir: Path) -> dict | None:
        """
        Load offline-precomputed U-Net inference results (precompute_inference.py,
        "variant B"). When present, the emulator replays real model output using
        only numpy+opencv — no torch/segmentation_models_pytorch in this image.
        """
        path = frames_dir / "precomputed.json"
        if not path.exists():
            return None
        try:
            with open(path) as f:
                bundle = json_lib.load(f)
            frames = bundle.get("frames", {})
            if not frames:
                print(f"[Camera] {path} has no frames — ignoring, falling back")
                return None
            print(f"[Camera] {len(frames)} precomputed inference results loaded "
                  f"from {path} (backend={bundle.get('backend', '?')}, "
                  f"threshold={bundle.get('threshold', '?')}) — replay mode, "
                  f"no model/torch required")
            return frames
        except (OSError, ValueError, KeyError) as exc:
            print(f"[Camera] Bad precomputed bundle {path}: {exc} — "
                  "falling back to live-model/opencv")
            return None

    def _make_synthetic_frames(self) -> list[dict]:
        """Deterministic synthetic sky frames — keeps demo/CI alive without data."""
        rng = random.Random(42)
        lines_per_frame = [0, 1, 2, 0, 3, 1, 0, 2]   # mix of clear / contrail skies
        frames = []
        h, w = 480, 640
        t = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
        base = np.dstack([                            # BGR gradient sky
            np.broadcast_to(180 - t * 60, (h, w)),
            np.broadcast_to(120 + t * 40, (h, w)),
            np.broadcast_to(80 + t * 60, (h, w)),
        ]).astype(np.float32)
        for i, n_lines in enumerate(lines_per_frame):
            noise = np.random.default_rng(100 + i).integers(-8, 8, (h, w, 3))
            img = np.clip(base + noise, 0, 255).astype(np.uint8)
            for _ in range(n_lines):
                y1 = rng.randint(20, h // 2 - 20)
                y2 = rng.randint(20, h // 2 - 20)
                cv2.line(img, (rng.randint(0, 60), y1),
                         (w - rng.randint(0, 60), y2), (245, 245, 255),
                         rng.randint(3, 6))
            img = cv2.GaussianBlur(img, (3, 3), 0)
            ref = f"synthetic_{i:05d}"
            self._synthetic[ref] = img
            frames.append({"frame_ref": ref, "path": None})
        return frames

    # ── Inference backends ─────────────────────────────────────────────────────

    def _init_detector(self):
        try:
            if INFERENCE_DIR not in sys.path:
                sys.path.insert(0, INFERENCE_DIR)
            from inference import ContrailDetector  # noqa: PLC0415
            # WEIGHTS_PATH: optional .pt override (e.g. edge-pi/data/
            # contrail_unet_best.pt) — without it ContrailDetector checks its
            # default weights dir and falls back to its OpenCV heuristic.
            weights = os.getenv("WEIGHTS_PATH")
            det = ContrailDetector(weights_path=weights) if weights \
                else ContrailDetector()
            print(f"[Camera] ContrailDetector ready — "
                  f"backend={getattr(det, '_backend', '?')}")
            return det
        except Exception as exc:
            print(f"[Camera] inference.py unavailable ({exc}) — "
                  "built-in OpenCV heuristic fallback")
            return None

    def _detect(self, frame) -> tuple[bool, float, float, "np.ndarray"]:
        """→ (detected, confidence, pixel_ratio, binary mask 0/255 full-res)."""
        if self.detector is not None:
            r = self.detector.detect(frame)
            return (bool(r.contrail_detected), float(r.confidence),
                    float(r.pixel_ratio), r.mask)
        return self._heuristic(frame)

    @staticmethod
    def _heuristic(frame) -> tuple[bool, float, float, "np.ndarray"]:
        """Mirror of inference.py OpenCV fallback — bright straight lines in sky."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        sky  = gray[:gray.shape[0] // 2, :]
        _, bright = cv2.threshold(sky, 200, 255, cv2.THRESH_BINARY)
        edges = cv2.Canny(bright, 50, 150)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=80,
                                minLineLength=80, maxLineGap=20)
        sky_mask = np.zeros(sky.shape[:2], dtype=np.uint8)
        if lines is not None:
            for x1, y1, x2, y2 in lines.reshape(-1, 4):
                cv2.line(sky_mask, (int(x1), int(y1)), (int(x2), int(y2)), 255, 8)
        mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        mask[:sky.shape[0]] = sky_mask
        pixel_ratio = float((mask > 0).sum()) / mask.size
        confidence  = min(pixel_ratio * 20, 0.85)
        return pixel_ratio > PIXEL_RATIO_MIN, confidence, pixel_ratio, mask

    # ── Per-frame analysis ─────────────────────────────────────────────────────

    @staticmethod
    def _downscale_mask(mask):
        h, w = mask.shape[:2]
        scale = MASK_MAX_SIDE / max(h, w)
        if scale >= 1.0:
            return mask
        return cv2.resize(mask, (max(1, int(w * scale)), max(1, int(h * scale))),
                          interpolation=cv2.INTER_NEAREST)

    def _temporal_delta(self, camera_id: str, binary: "np.ndarray") -> tuple[int, int]:
        """
        binary: 0/1 mask at MASK_MAX_SIDE scale for THIS camera's current frame.
        → (contrail_count, new_contrail_count).

        Connected components = individual contrail instances. A component is "new"
        when it has zero overlap with the (dilated) previous frame's mask for this
        camera. Shared by both the live-model/opencv path and the precomputed-replay
        path so the delta semantics are identical regardless of inference source.
        """
        n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        valid = [lab for lab in range(1, n_labels)
                 if stats[lab, cv2.CC_STAT_AREA] >= MIN_COMPONENT_PX]
        contrail_count = len(valid)

        prev = self._prev_mask[camera_id]
        if prev is None or prev.shape != binary.shape:
            new_count = contrail_count
        else:
            prev_dil = cv2.dilate(prev, np.ones((7, 7), np.uint8))
            new_count = sum(1 for lab in valid
                            if not prev_dil[labels == lab].any())
        self._prev_mask[camera_id] = binary
        return contrail_count, new_count

    def _analyse_precomputed(self, camera_id: str, ref: str) -> dict:
        """
        Replay a real U-Net result computed offline by precompute_inference.py
        ("variant B"). Uses only numpy+opencv — no torch/segmentation_models_pytorch
        in this process. new_contrail_count is still derived at replay time via
        _temporal_delta, because the per-camera frame sequence (frames[k::n]) is a
        runtime concern, not something that can be baked into the offline bundle.
        """
        data = self._precomputed.get(ref)
        if data is None:
            raise ValueError(f"frame_ref {ref} missing from precomputed bundle")

        png = base64.b64decode(data["mask_small_b64"])
        small = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
        binary = (small > 0).astype(np.uint8)
        contrail_count, new_count = self._temporal_delta(camera_id, binary)

        pixel_ratio = float(data["pixel_ratio"])
        confidence  = float(data["confidence"])
        detected    = pixel_ratio > PIXEL_RATIO_MIN

        return {
            "message_type": "EDGE_VISION_AI",
            "camera_id": camera_id,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "contrail_detected": bool(detected and contrail_count > 0),
            "confidence": round(confidence, 3),
            "contrail_pixel_ratio": round(pixel_ratio, 6),
            "contrail_count": contrail_count,
            "new_contrail_count": new_count,
            "frame_ref": ref,
            "mask_png_b64": data["viz_jpeg_b64"],
        }

    def _analyse(self, camera_id: str, entry: dict) -> dict:
        ref = entry["frame_ref"]
        if self._precomputed is not None:
            return self._analyse_precomputed(camera_id, ref)

        if entry["path"] is None:
            frame = self._synthetic[ref]
        else:
            frame = cv2.imread(str(entry["path"]))
        if frame is None:
            raise ValueError(f"unreadable frame {entry['path']}")

        detected, confidence, pixel_ratio, mask = self._detect(frame)
        small  = self._downscale_mask((mask > 0).astype(np.uint8) * 255)
        binary = (small > 0).astype(np.uint8)

        contrail_count, new_count = self._temporal_delta(camera_id, binary)

        # Visualisation: downscaled camera frame with detected contrails painted red.
        # JPEG-encoded — a photographic frame as PNG is ~100-140 KB of base64, which blows
        # past the payload cap (120 KB) and strains Event Hub; JPEG q75 is ~8-11 KB.
        # (contrail_count is computed above so the red overlay only runs on real detections.)
        viz_frame = cv2.resize(frame, (small.shape[1], small.shape[0]))
        if detected and contrail_count > 0:
            viz_frame = viz_frame.copy()
            viz_frame[binary > 0] = [0, 0, 255]
        ok, buf = cv2.imencode(".jpg", viz_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
        mask_b64 = base64.b64encode(buf).decode("ascii") if ok else None

        return {
            "message_type": "EDGE_VISION_AI",
            "camera_id": camera_id,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            # detection must be consistent with the reported instance count
            "contrail_detected": bool(detected and contrail_count > 0),
            "confidence": round(confidence, 3),
            "contrail_pixel_ratio": round(pixel_ratio, 6),
            "contrail_count": contrail_count,
            "new_contrail_count": new_count,
            "frame_ref": ref,
            "mask_png_b64": mask_b64,
        }

    # ── Public API ─────────────────────────────────────────────────────────────

    def produce(self) -> list[dict]:
        """One EDGE_VISION_AI payload per camera (camera-keyed, no flight_id)."""
        if not self.enabled or not self._frames:
            return []
        events: list[dict] = []
        n = len(self.cameras)
        for k, cam in enumerate(self.cameras):
            sub = self._frames[k::n]     # time-sliced single physical camera
            if not sub:
                continue
            entry = sub[self._cursor[k] % len(sub)]
            self._cursor[k] += 1
            try:
                events.append(self._analyse(cam["id"], entry))
            except Exception as exc:     # one bad frame must not kill the loop
                print(f"[Camera] {cam['id']} frame {entry['frame_ref']} failed: {exc}")
        return events


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    global zones_cache, last_zone_refresh, LAST_SEND_TS

    conn_str = os.getenv("CONN_STR")
    if not conn_str:
        print("Error: CONN_STR environment variable is not set.")
        return

    start_health_server()

    # Option A — non-blocking start: one quick fetch_issr_zones() (short retries,
    # falls back to Alpha/Bravo on failure) instead of blocking up to 15 min in
    # wait_for_dynamic_zones(). First telemetry goes out within ~15-20 s of
    # container start. If we land on fallback, the main loop below polls every
    # FALLBACK_POLL_S (~60 s) — matching IssrZoneService's ~60 s initial publish
    # delay — until dynamic zones arrive, then drops back to the normal
    # ZONE_REFRESH_S (30 min) cadence.
    zones_cache = fetch_issr_zones()
    last_zone_refresh = time.time()

    _fallback_ids = {"ALPHA", "BRAVO"}
    on_fallback = {z["id"] for z in zones_cache}.issubset(_fallback_ids)

    init_simulation(zones_cache)
    camera_producer = CameraProducer()
    print(f"[COAV Emulator] Running — "
          f"{len(ROUTES)} transit routes + {len(HOLDS)} holds + 1 departure + 1 arrival "
          f"+ {len(camera_producer.cameras)} ground cameras"
          f"{' [fallback zones — will upgrade automatically]' if on_fallback else ''}")

    producer = EventHubProducerClient.from_connection_string(
        conn_str=conn_str, eventhub_name="telemetry-adsb-inbound"
    )
    try:
        with producer:
            while True:
                refresh_due_s = FALLBACK_POLL_S if on_fallback else ZONE_REFRESH_S
                if time.time() - last_zone_refresh > refresh_due_s:
                    new_zones = fetch_issr_zones()
                    new_ids   = {z["id"] for z in new_zones}
                    # Reinitialise routes whenever the zone GEOMETRY changes — not only on the
                    # first fallback→dynamic upgrade. This lets a running emulator self-heal when
                    # IssrZoneService publishes new/reshaped zones (backend redeploy, or a 30-min
                    # Open-Meteo shift) so routes track the real ISSR area — NO manual container
                    # restart needed.
                    if _zone_signature(new_zones) != _zone_signature(zones_cache):
                        print(f"[Emulator] Zone geometry changed → reinitialising routes "
                              f"({sorted(new_ids)})")
                        zones_cache = new_zones
                        init_simulation(zones_cache)
                    on_fallback = new_ids.issubset(_fallback_ids)
                    last_zone_refresh = time.time()

                adsb_payloads   = build_payloads()
                camera_payloads = camera_producer.produce()
                try:
                    batch = producer.create_batch()
                    for raw in adsb_payloads + camera_payloads:
                        msg = MODEL_BY_TYPE[raw["message_type"]](**raw)
                        batch.add(EventData(msg.model_dump_json()))
                        if raw["message_type"] == "ADSB_TELEMETRY":
                            print(f"  [x] {raw['message_type']:20s} {raw['flight_id']:8s} "
                                  f"lat={raw['latitude']:.3f} lon={raw['longitude']:.3f} "
                                  f"alt={raw['altitude_ft']}ft spd={raw['speed_knots']}kt")
                        else:
                            print(f"  [x] {raw['message_type']:20s} {raw['camera_id']:10s} "
                                  f"frame={raw['frame_ref']} "
                                  f"detected={raw['contrail_detected']} "
                                  f"conf={raw['confidence']:.2f} "
                                  f"contrails={raw['contrail_count']} "
                                  f"(new {raw['new_contrail_count']})")
                    producer.send_batch(batch)
                    LAST_SEND_TS = time.time()
                    print(f"  --- tick={tick} aircraft={len(adsb_payloads)} "
                          f"cameras={len(camera_payloads)} ---")
                except ValidationError as ve:
                    print(f"  [OWASP ALERT] Validation failed: {ve}")

                time.sleep(TICK_S)
    except KeyboardInterrupt:
        print("\n[COAV Emulator] Stopped.")


# Module-level init so tests can import ROUTE_HEADINGS, HOLDS, DEP_HEADING etc.
# without calling main() (which requires CONN_STR and a live backend).
init_simulation(list(FALLBACK_ZONES))
zones_cache = list(FALLBACK_ZONES)

if __name__ == "__main__":
    main()
