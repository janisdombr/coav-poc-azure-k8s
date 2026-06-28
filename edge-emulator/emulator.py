import time
import datetime
import os
import math
import random
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


# ── ISSR zones — MUAC sector (mirrors FlightStateStore.ISSR_ZONES) ─────────────
CRITICAL_ZONES = [
    (50.20, 51.00, 3.80, 5.40, 33000, 38000),  # Zone Alpha — Brussels convergence
    (51.30, 52.50, 5.80, 8.20, 31000, 37000),  # Zone Bravo — Dutch-German border
]

def is_inside_critical_zone(lat: float, lon: float, alt: int) -> bool:
    for zone in CRITICAL_ZONES:
        min_lat, max_lat, min_lon, max_lon, min_alt, max_alt = zone
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon and min_alt <= alt <= max_alt:
            return True
    return False


# ── Transit corridors (mirrors FlightSimulatorService.ROUTES) ─────────────────
# Each entry: (startLat, startLon, endLat, endLon)
ROUTES = [
    (50.20, 3.80, 52.80, 9.00),  # SW→NE  A7 / N871  Paris → Hamburg
    (51.50, 9.20, 50.70, 3.40),  # E→W    T180       Frankfurt → Brussels
    (49.80, 6.50, 52.90, 3.20),  # SE→NW  B317       Luxembourg → North Sea
    (49.40, 4.60, 53.30, 6.80),  # S→N    UN852      Reims → Frisian Islands
]
DURATIONS    = [950, 780, 870, 820]   # ticks to cross the sector
COOLDOWN_BASE = 130                    # ticks gap before next same-route flight
COOLDOWN_VAR  = 60
ALTITUDES    = [35000, 37000, 33000, 36000]
SPEEDS       = [475, 465, 480, 460]

ROUTE_AIRLINES = [
    ["BAW", "EZY", "VLG", "IBE", "TAP"],
    ["DLH", "AUA", "SWR", "BER", "WZZ"],
    ["KLM", "TRA", "DAT", "VLR", "DEN"],
    ["AFR", "TVF", "HOP", "XLR", "LFR"],
]
ROUTE_NUMBERS = [
    [214, 316, 429, 551, 682],
    [437, 593, 712, 821, 934],
    [871, 992, 104, 215, 328],
    [133, 267, 381, 475, 598],
]

# ── Holding stacks (fixed callsign, infinite circular orbit) ──────────────────
# Each entry: (centerLat, centerLon, radiusLat, radiusLon)
HOLDS = [
    (50.50, 4.80, 0.12, 0.19),  # Brussels  DENUT hold  FL350
    (52.30, 4.45, 0.10, 0.16),  # Amsterdam SUGOL hold  FL330
]
HOLD_ALTS   = [35000, 33000]
HOLD_SPEEDS = [265, 265]
HOLD_IDS    = ["BEL256", "KLM892"]
HOLD_OMEGA  = 2 * math.pi / 420.0  # one orbit ≈ 420 ticks (21 min at 3s/tick)

# ── Departure (one-shot: Maastricht Aachen Airport → northbound) ──────────────
DEP_ID       = "TUI6KL"
DEP_START    = (50.91, 5.77)
DEP_END      = (52.50, 4.20)
DEP_DURATION = 600


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """True bearing in degrees (0=N, 90=E) from point A to point B."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360

# Pre-compute fixed headings per transit route (mirrors FlightSimulatorService.ROUTE_HEADINGS)
ROUTE_HEADINGS = [
    _bearing(ROUTES[i][0], ROUTES[i][1], ROUTES[i][2], ROUTES[i][3])
    for i in range(len(ROUTES))
]
DEP_HEADING = _bearing(DEP_START[0], DEP_START[1], DEP_END[0], DEP_END[1])


# ── Mutable simulator state ────────────────────────────────────────────────────

def make_callsign(route_idx: int, airline_idx: int) -> str:
    return ROUTE_AIRLINES[route_idx][airline_idx] + str(ROUTE_NUMBERS[route_idx][airline_idx])


# Stagger initial progress so aircraft start spread across their routes
route_progress    = [int(DURATIONS[i] * (i + 1) / (len(ROUTES) + 1)) for i in range(len(ROUTES))]
route_active      = [True] * len(ROUTES)
route_cooldown    = [0] * len(ROUTES)
route_airline_idx = [0] * len(ROUTES)
route_flight_id   = [make_callsign(i, 0) for i in range(len(ROUTES))]

dep_progress = 0
dep_done     = False
tick         = 0


def build_payloads() -> list[dict]:
    """
    Advance simulation by one tick and return the list of telemetry event dicts.
    Transit flights exit the sector naturally, then a new aircraft with a different
    callsign starts from the route origin after a gap.  Holding aircraft keep the
    same callsign indefinitely.  Mirrors FlightSimulatorService.java tick() logic.
    """
    global tick, dep_progress, dep_done
    global route_progress, route_active, route_cooldown, route_airline_idx, route_flight_id

    tick += 1
    iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    active_aircraft: list[tuple] = []  # (flight_id, lat, lon, alt, speed, heading)

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
            # Exited sector — stop publishing; Java FlightStateStore 5-min TTL removes it
            route_active[i]   = False
            route_cooldown[i] = COOLDOWN_BASE + random.randint(0, COOLDOWN_VAR)
            continue

        t   = route_progress[i] / DURATIONS[i]
        lat = ROUTES[i][0] + t * (ROUTES[i][2] - ROUTES[i][0])
        lon = ROUTES[i][1] + t * (ROUTES[i][3] - ROUTES[i][1])
        alt = ALTITUDES[i] + int(math.sin(tick * 0.003 + i) * 200)
        active_aircraft.append((route_flight_id[i], lat, lon, alt, SPEEDS[i], ROUTE_HEADINGS[i]))

    # ── 2. Holding stacks (fixed callsign, endless orbit) ─────────────────────
    for h in range(len(HOLDS)):
        angle = tick * HOLD_OMEGA + h * math.pi
        lat   = HOLDS[h][0] + HOLDS[h][2] * math.sin(angle)
        lon   = HOLDS[h][1] + HOLDS[h][3] * math.cos(angle)
        alt   = HOLD_ALTS[h] + int(math.sin(tick * 0.002 + h) * 100)
        r_lat = HOLDS[h][2]
        r_lon = HOLDS[h][3]
        hdg   = (math.degrees(math.atan2(-r_lon * math.sin(angle), r_lat * math.cos(angle))) + 360) % 360
        active_aircraft.append((HOLD_IDS[h], lat, lon, alt, HOLD_SPEEDS[h], round(hdg, 1)))

    # ── 3. Departure (one-shot) ────────────────────────────────────────────────
    if not dep_done:
        dep_progress += 1
        t   = dep_progress / DEP_DURATION
        lat = DEP_START[0] + t * (DEP_END[0] - DEP_START[0])
        lon = DEP_START[1] + t * (DEP_END[1] - DEP_START[1])
        alt = int(10000 + (t / 0.4) * 25000) if t < 0.4 else 35000 + int(math.sin(tick * 0.003) * 100)
        spd = int(280 + (t / 0.4) * 195) if t < 0.4 else 475
        active_aircraft.append((DEP_ID, lat, lon, min(alt, 35200), min(spd, 475), DEP_HEADING))
        if dep_progress >= DEP_DURATION:
            dep_done = True

    # ── Build event pairs (ADSB + EDGE_VISION_AI) for each aircraft ───────────
    events: list[dict] = []
    for fid, lat, lon, alt, spd, hdg in active_aircraft:
        in_zone = is_inside_critical_zone(lat, lon, alt)
        conf    = round(0.91 + 0.05 * math.sin(tick * 0.1), 2) if in_zone else 0.95

        events.append({
            "message_type": "ADSB_TELEMETRY",
            "flight_id": fid,
            "timestamp": iso,
            "latitude": round(lat, 5),
            "longitude": round(lon, 5),
            "altitude_ft": alt,
            "speed_knots": spd,
            "heading": round(hdg, 1),
        })
        events.append({
            "message_type": "EDGE_VISION_AI",
            "camera_id": "STATION-BE-01",
            "flight_id": fid,
            "timestamp": iso,
            "latitude": round(lat, 5),
            "longitude": round(lon, 5),
            "altitude_ft": alt,
            "speed_knots": spd,
            "contrail_detected": in_zone,
            "confidence_score": conf,
        })

    return events


def main():
    conn_str = os.getenv("CONN_STR")
    if not conn_str:
        print("Error: CONN_STR environment variable is not set.")
        return

    eventhub_name = "telemetry-adsb-inbound"
    producer = EventHubProducerClient.from_connection_string(
        conn_str=conn_str, eventhub_name=eventhub_name
    )
    print(f"[COAV Emulator] Sending to Event Hub: {eventhub_name}")
    print(f"[COAV Emulator] {len(ROUTES)} transit routes + {len(HOLDS)} holding stacks + 1 departure")

    try:
        with producer:
            while True:
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

                time.sleep(3)
    except KeyboardInterrupt:
        print("\n[COAV Emulator] Stopped.")


if __name__ == "__main__":
    main()
