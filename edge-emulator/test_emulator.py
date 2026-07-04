import math
import pytest
from pydantic import ValidationError
from emulator import (
    ADSBTelemetry, build_payloads,
    ROUTE_HEADINGS, DEP_HEADING, ARR_HEADING, HOLDS, HOLD_OMEGA,
)


# ── Schema / output shape ─────────────────────────────────────────────────────

def test_build_payloads_returns_events():
    payloads = build_payloads()
    assert len(payloads) > 0


def test_each_aircraft_emits_adsb_and_vision_pair():
    payloads = build_payloads()
    types = [p["message_type"] for p in payloads]
    assert types.count("ADSB_TELEMETRY") == types.count("EDGE_VISION_AI")


def test_all_payloads_pass_schema_validation():
    """Every generated payload must satisfy the Pydantic model (OWASP A03 gate)."""
    for raw in build_payloads():
        ADSBTelemetry(**raw)  # raises ValidationError on any violation


def test_adsb_payloads_contain_heading():
    """ADSB_TELEMETRY messages must include heading so the Java backend can do trajectory projection."""
    for raw in build_payloads():
        if raw["message_type"] == "ADSB_TELEMETRY":
            assert "heading" in raw, f"Missing heading in {raw['flight_id']}"
            assert 0.0 <= raw["heading"] < 360.0, f"heading out of range: {raw['heading']}"


def test_vision_ai_payloads_have_no_heading():
    """EDGE_VISION_AI messages are camera events — no heading field needed."""
    for raw in build_payloads():
        if raw["message_type"] == "EDGE_VISION_AI":
            assert "heading" not in raw


def test_flight_ids_match_muac_callsign_format():
    """Callsigns must be ICAO airline code + flight number (e.g. EZY214, DLH437)."""
    for raw in build_payloads():
        fid = raw["flight_id"]
        assert fid.isalnum(), f"Non-alphanumeric flight_id: {fid}"
        assert 3 <= len(fid) <= 12


# ── Heading geometry ──────────────────────────────────────────────────────────

def test_route_headings_count_matches_routes():
    from emulator import ROUTES
    assert len(ROUTE_HEADINGS) == len(ROUTES)


def test_route_headings_are_valid_bearings():
    for i, hdg in enumerate(ROUTE_HEADINGS):
        assert 0.0 <= hdg < 360.0, f"Route {i} heading {hdg} out of range"


def test_route_0_heading_is_westward():
    # Route 0: enters ISSR zone from east → flies west, expect heading ~230–300°
    assert 230.0 < ROUTE_HEADINGS[0] < 300.0, f"Expected W, got {ROUTE_HEADINGS[0]}"


def test_route_1_heading_is_northward():
    # Route 1: enters ISSR zone from south → flies north, expect heading near 0°
    hdg = ROUTE_HEADINGS[1]
    assert hdg > 335.0 or hdg < 25.0, f"Expected N, got {hdg}"


def test_route_2_heading_is_southwestward():
    # Route 2: enters ISSR zone from north-east → flies SW, expect heading ~190–260°
    assert 190.0 < ROUTE_HEADINGS[2] < 260.0, f"Expected SW, got {ROUTE_HEADINGS[2]}"


def test_route_3_heading_is_westward():
    # Route 3: above zone ceiling (WARNING only), flies east → west, expect ~230–300°
    assert 230.0 < ROUTE_HEADINGS[3] < 300.0, f"Expected W, got {ROUTE_HEADINGS[3]}"


def test_departure_heading_is_northward():
    # TUI6KL: departs Maastricht Aachen Airport northward into zone, expect near-north
    hdg = DEP_HEADING
    assert hdg < 30.0 or hdg > 330.0, f"Expected N, got {hdg}"


def test_arrival_heading_is_southward():
    # RYR912: descends from north of zone to Maastricht Aachen Airport, expect S/SE
    assert 130.0 < ARR_HEADING < 230.0, f"Expected S/SE, got {ARR_HEADING}"


def test_holding_tangent_heading_changes_per_tick():
    """Holding orbit heading must vary with angle — not a constant."""
    headings = set()
    for tick_offset in range(0, 100, 10):
        angle = tick_offset * HOLD_OMEGA
        r_lat = HOLDS[0][2]
        r_lon = HOLDS[0][3]
        hdg = (math.degrees(math.atan2(-r_lon * math.sin(angle), r_lat * math.cos(angle))) + 360) % 360
        headings.add(round(hdg, 1))
    assert len(headings) > 1, "Holding heading should change with orbit position"


def test_holding_tangent_heading_full_circle():
    """Over a full orbit the holding stack heading must cover all four quadrants."""
    orbit_ticks = int(2 * math.pi / HOLD_OMEGA)
    headings = []
    for t in range(orbit_ticks):
        angle = t * HOLD_OMEGA
        r_lat = HOLDS[0][2]
        r_lon = HOLDS[0][3]
        hdg = (math.degrees(math.atan2(-r_lon * math.sin(angle), r_lat * math.cos(angle))) + 360) % 360
        headings.append(hdg)
    assert min(headings) < 90.0
    assert max(headings) > 270.0


# ── OWASP A03 — input validation (security boundary) ─────────────────────────

def test_invalid_latitude_overflow():
    with pytest.raises(ValidationError):
        ADSBTelemetry(
            message_type="ADSB_TELEMETRY", flight_id="EZY214",
            timestamp="2026-06-29T00:00:00Z",
            latitude=95.0, longitude=4.60, altitude_ft=35000, speed_knots=450,
        )


def test_invalid_longitude_underflow():
    with pytest.raises(ValidationError):
        ADSBTelemetry(
            message_type="ADSB_TELEMETRY", flight_id="DLH437",
            timestamp="2026-06-29T00:00:00Z",
            latitude=51.0, longitude=-190.0, altitude_ft=35000, speed_knots=450,
        )


def test_invalid_heading_out_of_range():
    with pytest.raises(ValidationError):
        ADSBTelemetry(
            message_type="ADSB_TELEMETRY", flight_id="KLM871",
            timestamp="2026-06-29T00:00:00Z",
            latitude=51.0, longitude=5.0, altitude_ft=35000, speed_knots=450,
            heading=400.0,
        )


def test_flight_id_regex_injection():
    """Special characters in flight_id must be rejected (command injection prevention)."""
    with pytest.raises(ValidationError):
        ADSBTelemetry(
            message_type="ADSB_TELEMETRY", flight_id="COAV;DROP",
            timestamp="2026-06-29T00:00:00Z",
            latitude=51.0, longitude=4.5, altitude_ft=35000, speed_knots=450,
        )


def test_flight_id_too_short():
    with pytest.raises(ValidationError):
        ADSBTelemetry(
            message_type="ADSB_TELEMETRY", flight_id="AB",
            timestamp="2026-06-29T00:00:00Z",
            latitude=51.0, longitude=4.5, altitude_ft=35000, speed_knots=450,
        )


def test_altitude_negative_rejected():
    with pytest.raises(ValidationError):
        ADSBTelemetry(
            message_type="ADSB_TELEMETRY", flight_id="AFR133",
            timestamp="2026-06-29T00:00:00Z",
            latitude=51.0, longitude=4.5, altitude_ft=-1, speed_knots=450,
        )


def test_valid_heading_boundary_values():
    """Heading at 0.0 and 359.9 must be accepted."""
    for hdg in (0.0, 359.9):
        ADSBTelemetry(
            message_type="ADSB_TELEMETRY", flight_id="BEL256",
            timestamp="2026-06-29T00:00:00Z",
            latitude=50.5, longitude=4.8, altitude_ft=35000, speed_knots=265,
            heading=hdg,
        )
