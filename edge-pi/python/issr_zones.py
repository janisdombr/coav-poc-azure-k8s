"""
Real-time ISSR (Ice Super-Saturated Region) zone computation.

Data source: Open-Meteo free API — no registration, no API key required.
Update interval: every 30 minutes (Open-Meteo updates every hour).

Physics:
    Open-Meteo returns RH with respect to water (RHw).
    ISSR requires RH with respect to ice (RHi).
    Conversion: RHi = RHw × (e_sat_water(T) / e_sat_ice(T))
    ISSR when RHi > 100% at cruise altitude (FL300–FL390, ~200–300 hPa)

Reference: Murphy & Koop (2005), "Review of the vapour pressures of ice and
supercooled water for atmospheric applications", QJRMS 131:1539–1565.
"""

import json
import math
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

# MUAC region bounding box — wider than hardcoded zones to catch emerging ISSR
REGION = dict(lat_min=49.5, lat_max=53.5, lon_min=2.0, lon_max=10.0)
GRID_STEPS_LAT = 6   # ~0.7° spacing
GRID_STEPS_LON = 8   # ~1.0° spacing

# FL330–FL390 ≈ 250 hPa (cruise band where contrails form)
# FL300–FL330 ≈ 300 hPa (lower cruise)
PRESSURE_LEVELS = [("250hPa", 34_000), ("300hPa", 30_000)]  # (level, approx_ft)

RHI_THRESHOLD   = 100.0   # % — ISSR definition
RHI_MIN_CLUSTER = 2       # minimum adjacent grid points to form a zone


@dataclass
class IssrZone:
    id:       str
    min_lat:  float
    max_lat:  float
    min_lon:  float
    max_lon:  float
    min_alt:  int     # feet
    max_alt:  int     # feet
    rhi_max:  float   # max RHi observed in zone (intensity indicator)
    valid_at: str     # ISO timestamp


# ── Physics ────────────────────────────────────────────────────────────────────

def _e_sat_water(T_C: float) -> float:
    """Saturation vapor pressure over liquid water, hPa (Buck 1981)."""
    return 6.1078 * math.exp(17.27 * T_C / (T_C + 237.3))


def _e_sat_ice(T_C: float) -> float:
    """Saturation vapor pressure over ice, hPa (Murphy & Koop 2005)."""
    T_K = T_C + 273.15
    ln_e = (9.550426 - 5723.265 / T_K
            + 3.53068 * math.log(T_K)
            - 0.00728332 * T_K)
    return math.exp(ln_e) / 100.0   # Pa → hPa


def rhi_from_rhw(rh_water_pct: float, T_C: float) -> float:
    """Convert RH over water → RH over ice (%). Only meaningful for T < 0°C."""
    if T_C >= 0.0 or rh_water_pct <= 0:
        return rh_water_pct
    return rh_water_pct * _e_sat_water(T_C) / _e_sat_ice(T_C)


# ── Open-Meteo fetch ───────────────────────────────────────────────────────────

def _fetch_point(lat: float, lon: float, hour_offset: int = 0) -> dict:
    """Fetch temperature + RHw at 250 hPa and 300 hPa for one grid point."""
    fields = ",".join(
        f"temperature_{lvl},relative_humidity_{lvl}"
        for lvl, _ in PRESSURE_LEVELS
    )
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat:.2f}&longitude={lon:.2f}"
        f"&hourly={fields}&forecast_days=2"
    )
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.load(r)


def _compute_grid(hour_offset: int = 0) -> list[dict]:
    """
    Query a grid of points over the MUAC region.
    hour_offset=0 → now, hour_offset=5 → +5h forecast (pre-tactical planning).
    Returns list of {lat, lon, level, alt_ft, rhi, is_issr}.
    """
    lats = [
        REGION["lat_min"] + i * (REGION["lat_max"] - REGION["lat_min"]) / (GRID_STEPS_LAT - 1)
        for i in range(GRID_STEPS_LAT)
    ]
    lons = [
        REGION["lon_min"] + i * (REGION["lon_max"] - REGION["lon_min"]) / (GRID_STEPS_LON - 1)
        for i in range(GRID_STEPS_LON)
    ]

    results = []
    for lat in lats:
        for lon in lons:
            try:
                data = _fetch_point(lat, lon)
                h = data["hourly"]
                for level, alt_ft in PRESSURE_LEVELS:
                    T  = h[f"temperature_{level}"][hour_offset]
                    rw = h[f"relative_humidity_{level}"][hour_offset]
                    ri = rhi_from_rhw(rw, T)
                    results.append(dict(
                        lat=round(lat, 2), lon=round(lon, 2),
                        level=level, alt_ft=alt_ft,
                        temp_c=T, rhw=rw, rhi=round(ri, 1),
                        is_issr=ri > RHI_THRESHOLD,
                    ))
            except Exception:
                pass   # skip failed grid points, don't break the whole scan

    return results


# ── Zone detection ─────────────────────────────────────────────────────────────

def _cluster_to_zones(points: list[dict]) -> list[IssrZone]:
    """
    Group adjacent ISSR grid points into rectangular bounding-box zones.
    Simple flood-fill on the 2D grid — adequate for sparse ISSR regions.
    """
    issr = [p for p in points if p["is_issr"]]
    if not issr:
        return []

    # Group by altitude level first
    by_level: dict[str, list[dict]] = {}
    for p in issr:
        by_level.setdefault(p["level"], []).append(p)

    zones: list[IssrZone] = []
    zone_id = 0

    for level, pts in by_level.items():
        if len(pts) < RHI_MIN_CLUSTER:
            continue

        # Simple connected-components via lat/lon proximity
        lat_step = (REGION["lat_max"] - REGION["lat_min"]) / (GRID_STEPS_LAT - 1)
        lon_step = (REGION["lon_max"] - REGION["lon_min"]) / (GRID_STEPS_LON - 1)
        threshold = max(lat_step, lon_step) * 1.5

        remaining = list(pts)
        while remaining:
            cluster = [remaining.pop(0)]
            changed = True
            while changed:
                changed = False
                next_remaining = []
                for p in remaining:
                    near = any(
                        abs(p["lat"] - c["lat"]) <= threshold and
                        abs(p["lon"] - c["lon"]) <= threshold
                        for c in cluster
                    )
                    if near:
                        cluster.append(p)
                        changed = True
                    else:
                        next_remaining.append(p)
                remaining = next_remaining

            if len(cluster) < RHI_MIN_CLUSTER:
                continue

            zone_id += 1
            alt_ft = cluster[0]["alt_ft"]
            # Add ±2000 ft margin around the pressure level
            zones.append(IssrZone(
                id      = f"Dynamic-{chr(64 + zone_id)}",
                min_lat = round(min(p["lat"] for p in cluster) - lat_step / 2, 2),
                max_lat = round(max(p["lat"] for p in cluster) + lat_step / 2, 2),
                min_lon = round(min(p["lon"] for p in cluster) - lon_step / 2, 2),
                max_lon = round(max(p["lon"] for p in cluster) + lon_step / 2, 2),
                min_alt = alt_ft - 2_000,
                max_alt = alt_ft + 2_000,
                rhi_max = round(max(p["rhi"] for p in cluster), 1),
                valid_at= datetime.now(timezone.utc).isoformat(),
            ))

    return zones


# ── Public API ─────────────────────────────────────────────────────────────────

def compute_issr_zones(hour_offset: int = 0) -> list[IssrZone]:
    """
    Compute current or forecast ISSR zones over the MUAC region.

    Args:
        hour_offset: 0 = now, 5 = +5h forecast (use for pre-tactical routing)

    Returns:
        List of IssrZone objects with bounding boxes in lat/lon/ft.
    """
    grid = _compute_grid(hour_offset)
    return _cluster_to_zones(grid)


def zones_to_json(zones: list[IssrZone]) -> str:
    """Serialise zones to JSON — compatible with /api/issr-zones response format."""
    return json.dumps([asdict(z) for z in zones], indent=2)


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Compute real-time ISSR zones from Open-Meteo")
    ap.add_argument("--hours", type=int, default=0,
                    help="Forecast offset in hours (0=now, 5=+5h pre-tactical)")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    ap.add_argument("--verbose", action="store_true", help="Print full grid")
    args = ap.parse_args()

    print(f"Fetching ISSR zones for MUAC region "
          f"({'now' if args.hours == 0 else f'+{args.hours}h forecast'})...\n")

    grid = _compute_grid(args.hours)

    if args.verbose:
        print(f"{'Lat':>6} {'Lon':>6} {'Level':>8} {'T°C':>6} {'RHw':>6} {'RHi':>7} {'ISSR?'}")
        print("-" * 54)
        for p in grid:
            print(f"{p['lat']:>6.2f} {p['lon']:>6.2f} {p['level']:>8} "
                  f"{p['temp_c']:>6.1f} {p['rhw']:>5.0f}% {p['rhi']:>6.1f}%"
                  f"  {'ISSR ←' if p['is_issr'] else ''}")
        issr_count = sum(1 for p in grid if p["is_issr"])
        print(f"\nISSR grid points: {issr_count}/{len(grid)}\n")

    zones = _cluster_to_zones(grid)

    if args.json:
        print(zones_to_json(zones))
    else:
        if not zones:
            print("No ISSR zones detected in MUAC region right now.")
        else:
            print(f"Detected {len(zones)} ISSR zone(s):\n")
            for z in zones:
                print(f"  Zone {z.id}")
                print(f"    Lat:  {z.min_lat}–{z.max_lat}°N")
                print(f"    Lon:  {z.min_lon}–{z.max_lon}°E")
                print(f"    Alt:  FL{z.min_alt//100}–FL{z.max_alt//100}")
                print(f"    RHi max: {z.rhi_max}%  (> 100% = contrails will persist)")
                print()
            print(f"For flight planning use --hours 5 for +5h pre-tactical forecast.")
