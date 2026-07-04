import time
import datetime
import os
import math
import random
import json as json_lib
import urllib.request
from typing import Literal
from pydantic import BaseModel, Field, ValidationError
from azure.eventhub import EventHubProducerClient, EventData

# ── Telemetry schema (OWASP A03:2021 — validation before sending) ─────────────
class ADSBTelemetry(BaseModel):
    message_type: Literal["ADSB_TELEMETRY", "EDGE_VISION_AI"]
    flight_id: str = Field(..., min_length=3, max_length=12, pattern=r"^[A-Z0-9\-]+$")
    timestamp: str
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    altitude_ft: int = Field(..., ge=0, le=60000)
    speed_knots: int = Field(..., ge=0, le=1000)
    heading: float | None = Field(None, ge=0.0, le=360.0)
    camera_id: str | None = Field(None, min_length=3, max_length=20)
    contrail_detected: bool | None = None
    confidence_score: float | None = Field(None, ge=0.0, le=1.0)


# ── ISSR zone management — single source of truth from backend API ─────────────

BACKEND_URL    = os.getenv("BACKEND_URL", "http://localhost:8080")
ZONE_REFRESH_S = 30 * 60   # re-fetch every 30 min (matches IssrZoneService)
TICK_S         = 3          # seconds per simulation tick

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


def is_inside_zone(lat: float, lon: float, alt: int,
                   zones: list[dict]) -> bool:
    """Full zone membership: lat/lon AND altitude."""
    for z in zones:
        if (z["minLat"] <= lat <= z["maxLat"] and
                z["minLon"] <= lon <= z["maxLon"] and
                z["minAlt"] <= alt <= z["maxAlt"]):
            return True
    return False


def is_contrail_detectable(lat: float, lon: float, alt: int,
                           zones: list[dict]) -> bool:
    """
    Camera detects a contrail when:
      - Flight is fully inside an ISSR zone (lat/lon + altitude), OR
      - Flight is inside zone lat/lon but within 4 000 ft ABOVE the zone ceiling.
        Reason: the ISSR upper boundary is diffuse; air just above the zone is
        still cold and humid enough for short-lived contrails.  This produces
        alert=WARNING on the backend (contrailDetected=True, issrZone=False).
    """
    for z in zones:
        in_latlon = (z["minLat"] <= lat <= z["maxLat"] and
                     z["minLon"] <= lon <= z["maxLon"])
        if not in_latlon:
            continue
        if z["minAlt"] <= alt <= z["maxAlt"]:
            return True                           # fully inside zone
        if z["maxAlt"] < alt <= z["maxAlt"] + 4000:
            return True                           # near-ISSR ceiling
    return False


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
    Derive simulation parameters from zone geometry so that all four alert
    states are always visible:

      CRITICAL   — holding stacks orbit inside the zone
      APPROACHING — transit routes 0–2 enter the zone from outside (start
                    at least 2.2° lat/lon clear of the boundary)
      WARNING    — route 3 flies above zone ceiling within lat/lon bounds
                   (contrail detectable via near-ISSR logic, not inside zone)
      null       — transit routes 0–2 when they have exited the far side
    """
    ml = min(z["minLat"] for z in zones);  xl = max(z["maxLat"] for z in zones)
    mn = min(z["minLon"] for z in zones);  xn = max(z["maxLon"] for z in zones)
    ma = min(z["minAlt"] for z in zones);  xa = max(z["maxAlt"] for z in zones)

    clat     = (ml + xl) / 2
    clon     = (mn + xn) / 2
    mid_alt  = int((ma + xa) / 2)          # e.g. FL340 for FL320–360
    over_alt = xa + 3000                    # above ceiling → WARNING

    # Approach buffer: 2.2° guarantees > 8 min APPROACHING phase before zone entry
    BUF = 2.2

    # (startLat, startLon, endLat, endLon) — stagger initial progress so all
    # four phases (outside → APPROACHING → CRITICAL → exited) are visible from
    # the first tick
    routes = [
        # 0  East → West at zone cruise alt  [APPROACHING then CRITICAL then null]
        (round(clat + 0.4, 2), round(xn + BUF, 2),
         round(clat - 0.4, 2), round(mn - 1.5, 2)),
        # 1  South → North at zone cruise alt [APPROACHING then CRITICAL then null]
        (round(ml - BUF, 2),   round(clon + 0.2, 2),
         round(xl + 1.5, 2),   round(clon - 0.2, 2)),
        # 2  North-East → South-West          [APPROACHING then CRITICAL then null]
        (round(xl + 1.2, 2),   round(xn + 1.2, 2),
         round(ml - 1.0, 2),   round(mn - 1.0, 2)),
        # 3  East → West ABOVE zone ceiling    [WARNING only, never CRITICAL]
        (round(clat + 1.2, 2), round(xn + 2.5, 2),
         round(clat - 1.2, 2), round(mn - 1.5, 2)),
    ]

    altitudes = [mid_alt, mid_alt, mid_alt + 1000, over_alt]
    speeds    = [460, 450, 475, 465]
    headings  = [_bearing(*r) for r in routes]

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
        ["WZZ", "HOP", "XLR", "TRA", "LFR"],   # Above zone (WARNING)
    ]
    numbers = [
        [437, 214, 316, 551, 682],
        [133, 267, 871, 104, 429],
        [593, 712, 821, 215, 328],
        [934, 381, 475, 992, 598],
    ]

    # Holding stacks — orbit inside zone → always CRITICAL
    holds = [
        (round(clat - 0.4, 2), round(clon - 0.5, 2), 0.12, 0.18),
        (round(clat + 0.5, 2), round(clon + 0.5, 2), 0.10, 0.15),
    ]
    hold_alts = [mid_alt, mid_alt - 1000]

    # Departure: climbs from Maastricht Aachen Airport (EHBK) northward into zone
    dep_start = (MAASTRICHT_LAT, MAASTRICHT_LON)
    dep_end   = (round(xl + 0.5, 2), round(clon + 0.3, 2))
    dep_hdg   = _bearing(dep_start[0], dep_start[1], dep_end[0], dep_end[1])

    # Arrival: descends from north of zone to Maastricht Aachen Airport (EHBK)
    arr_start = (round(xl + 0.5, 2), round(clon - 0.2, 2))
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

    # ── 4. Build event pairs — use live zones for contrail/ISSR truth ─────────
    events: list[dict] = []
    for fid, lat, lon, alt, spd, hdg in active:
        contrail = is_contrail_detectable(lat, lon, alt, zones_cache)
        conf     = round(0.88 + 0.08 * math.sin(tick * 0.1), 2) if contrail else 0.12
        events += [
            {
                "message_type": "ADSB_TELEMETRY",
                "flight_id": fid, "timestamp": iso,
                "latitude": round(lat, 5), "longitude": round(lon, 5),
                "altitude_ft": alt, "speed_knots": spd,
                "heading": round(hdg, 1),
            },
            {
                "message_type": "EDGE_VISION_AI",
                "camera_id": "STATION-BE-01",
                "flight_id": fid, "timestamp": iso,
                "latitude": round(lat, 5), "longitude": round(lon, 5),
                "altitude_ft": alt, "speed_knots": spd,
                "contrail_detected": contrail,
                "confidence_score": conf,
            },
        ]
    return events


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    global zones_cache, last_zone_refresh

    conn_str = os.getenv("CONN_STR")
    if not conn_str:
        print("Error: CONN_STR environment variable is not set.")
        return

    # Wait up to ~5 min for IssrZoneService to publish dynamic zones (initial delay ≈ 60 s).
    # If IssrZoneService's first run finds no ISSR conditions, backend stays on Alpha/Bravo
    # and the emulator falls back to those zones — but will auto-reinitialise when Dynamic
    # zones arrive in the next 30-min IssrZoneService cycle (see re-init logic below).
    zones_cache = wait_for_dynamic_zones()
    last_zone_refresh = time.time()

    _fallback_ids = {"ALPHA", "BRAVO"}
    on_fallback = {z["id"] for z in zones_cache}.issubset(_fallback_ids)

    init_simulation(zones_cache)
    print(f"[COAV Emulator] Running — "
          f"{len(ROUTES)} transit routes + {len(HOLDS)} holds + 1 departure + 1 arrival"
          f"{' [fallback zones — will upgrade automatically]' if on_fallback else ''}")

    producer = EventHubProducerClient.from_connection_string(
        conn_str=conn_str, eventhub_name="telemetry-adsb-inbound"
    )
    try:
        with producer:
            while True:
                if time.time() - last_zone_refresh > ZONE_REFRESH_S:
                    new_zones = fetch_issr_zones()
                    new_ids   = {z["id"] for z in new_zones}
                    if on_fallback and not new_ids.issubset(_fallback_ids):
                        # Zones upgraded fallback → dynamic: reinitialise routes so
                        # flight positions, holds, and departure/arrival all match the
                        # real ISSR area instead of the Alpha/Bravo placeholders.
                        print("[Emulator] Zones upgraded fallback → dynamic — reinitialising")
                        zones_cache = new_zones
                        init_simulation(zones_cache)
                        on_fallback = False
                    else:
                        zones_cache = new_zones
                        on_fallback = new_ids.issubset(_fallback_ids)
                    last_zone_refresh = time.time()

                raw_payloads = build_payloads()
                try:
                    batch = producer.create_batch()
                    for raw in raw_payloads:
                        telemetry = ADSBTelemetry(**raw)
                        batch.add(EventData(telemetry.model_dump_json()))
                        print(f"  [x] {raw['message_type']:20s} {raw['flight_id']:8s} "
                              f"lat={raw['latitude']:.3f} lon={raw['longitude']:.3f} "
                              f"alt={raw['altitude_ft']}ft spd={raw['speed_knots']}kt")
                    producer.send_batch(batch)
                    print(f"  --- tick={tick} aircraft={len(raw_payloads) // 2} ---")
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
