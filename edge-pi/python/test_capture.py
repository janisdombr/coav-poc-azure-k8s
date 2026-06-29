"""
Unit tests for capture.py — ADS-B parsing, track management, Pydantic validation.

Camera and Event Hub are NOT instantiated — only pure functions and data classes
are tested. Hardware-dependent code (open_camera, main loop) is excluded.
"""

import time
import pytest
from pydantic import ValidationError

# Import only the parts that don't require hardware or Azure credentials
from capture import AdsbTrack, Dump1090Reader, TelemetryEvent


# ── AdsbTrack ─────────────────────────────────────────────────────────────────

class TestAdsbTrack:
    def test_new_track_incomplete(self):
        t = AdsbTrack("AABBCC")
        assert not t.is_complete()

    def test_complete_requires_all_fields(self):
        t = AdsbTrack("AABBCC")
        t.callsign = "BAW123"
        t.lat      = 51.5
        t.lon      = 4.8
        t.altitude = 35000
        assert t.is_complete()

    def test_missing_callsign_is_incomplete(self):
        t = AdsbTrack("AABBCC")
        t.lat = 51.5; t.lon = 4.8; t.altitude = 35000
        assert not t.is_complete()

    def test_missing_lat_is_incomplete(self):
        t = AdsbTrack("AABBCC")
        t.callsign = "BAW123"; t.lon = 4.8; t.altitude = 35000
        assert not t.is_complete()

    def test_missing_lon_is_incomplete(self):
        t = AdsbTrack("AABBCC")
        t.callsign = "BAW123"; t.lat = 51.5; t.altitude = 35000
        assert not t.is_complete()

    def test_missing_altitude_is_incomplete(self):
        t = AdsbTrack("AABBCC")
        t.callsign = "BAW123"; t.lat = 51.5; t.lon = 4.8
        assert not t.is_complete()

    def test_fresh_track_not_stale(self):
        t = AdsbTrack("AABBCC")
        assert not t.stale(max_age_s=60.0)

    def test_old_track_is_stale(self):
        t = AdsbTrack("AABBCC")
        t.updated_at = time.monotonic() - 120   # 2 minutes ago
        assert t.stale(max_age_s=60.0)

    def test_stale_boundary(self):
        t = AdsbTrack("AABBCC")
        t.updated_at = time.monotonic() - 59
        assert not t.stale(max_age_s=60.0)


# ── Dump1090Reader SBS parsing ─────────────────────────────────────────────────

class TestSbsParsing:
    def _reader(self):
        r = Dump1090Reader()
        return r

    # MSG type 1 — callsign identification
    # SBS BaseStation format: 22 comma-separated fields (indices 0–21)
    # MSG,<type>,<sesID>,<acID>,<hexIdent>,<flID>,<dateGen>,<timeGen>,
    #     <dateLog>,<timeLog>,<callsign>,<alt>,<spd>,<track>,<lat>,<lon>,
    #     <vertRate>,<squawk>,<alert>,<emergency>,<SPI>,<onGround>

    def test_msg1_parses_callsign(self):
        r = self._reader()
        r._parse_sbs("MSG,1,1,1,4CA7B4,1,2024/01/01,12:00:00,2024/01/01,12:00:00,BAW456,,,,,,,,,,,0")
        track = r._tracks.get("4CA7B4")
        assert track is not None
        assert track.callsign == "BAW456"

    def test_msg1_ignores_empty_callsign(self):
        r = self._reader()
        r._parse_sbs("MSG,1,1,1,4CA7B4,1,2024/01/01,12:00:00,2024/01/01,12:00:00,,,,,,,,,,,,0")
        track = r._tracks.get("4CA7B4")
        if track:
            assert track.callsign is None

    # MSG type 3 — airborne position
    def test_msg3_parses_position(self):
        r = self._reader()
        r._parse_sbs("MSG,3,1,1,4CA7B4,1,2024/01/01,12:00:00,2024/01/01,12:00:00,,35000,,,51.500,4.800,,,,,,0")
        track = r._tracks["4CA7B4"]
        assert track.altitude == 35000
        assert abs(track.lat - 51.5) < 0.001
        assert abs(track.lon - 4.8)  < 0.001

    def test_msg3_handles_missing_fields(self):
        r = self._reader()
        r._parse_sbs("MSG,3,1,1,FFFFFF,1,2024/01/01,12:00:00,2024/01/01,12:00:00,,35000,,,,,,,,,,0")

    # MSG type 4 — airborne velocity
    def test_msg4_parses_speed_and_heading(self):
        r = self._reader()
        r._parse_sbs("MSG,4,1,1,4CA7B4,1,2024/01/01,12:00:00,2024/01/01,12:00:00,,,475.0,270.5,,,,,,,,0")
        track = r._tracks["4CA7B4"]
        assert track.speed   == 475
        assert abs(track.heading - 270.5) < 0.01

    def test_msg4_handles_missing_speed(self):
        r = self._reader()
        r._parse_sbs("MSG,4,1,1,FFFFFF,1,2024/01/01,12:00:00,2024/01/01,12:00:00,,,,,,,,,,,,0")

    # Non-MSG lines
    def test_ignores_non_msg_lines(self):
        r = self._reader()
        r._parse_sbs("")
        r._parse_sbs("STA,1,2,3")
        r._parse_sbs("AIR,MSG")
        assert len(r._tracks) == 0

    def test_ignores_short_lines(self):
        r = self._reader()
        r._parse_sbs("MSG,1,2")
        assert len(r._tracks) == 0

    # ICAO hex normalisation
    def test_icao_uppercased(self):
        r = self._reader()
        r._parse_sbs("MSG,1,1,1,4ca7b4,1,2024/01/01,12:00:00,2024/01/01,12:00:00,KLM892,,,,,,,,,,,0")
        assert "4CA7B4" in r._tracks

    # Multiple tracks
    def test_multiple_aircraft_tracked(self):
        r = self._reader()
        r._parse_sbs("MSG,1,1,1,AAA001,1,2024/01/01,12:00:00,2024/01/01,12:00:00,BAW123,,,,,,,,,,,0")
        r._parse_sbs("MSG,1,1,1,BBB002,1,2024/01/01,12:00:00,2024/01/01,12:00:00,KLM456,,,,,,,,,,,0")
        assert len(r._tracks) == 2

    # get_active_flights
    def test_only_complete_tracks_returned(self):
        r = self._reader()
        # Incomplete: no callsign
        r._parse_sbs("MSG,3,1,1,AAABBB,1,2024/01/01,12:00:00,2024/01/01,12:00:00,,35000,,,51.5,4.8,,,,,,0")
        # Complete
        r._parse_sbs("MSG,1,1,1,CCCDDD,1,2024/01/01,12:00:00,2024/01/01,12:00:00,EZY999,,,,,,,,,,,0")
        r._parse_sbs("MSG,3,1,1,CCCDDD,1,2024/01/01,12:00:00,2024/01/01,12:00:00,,35000,,,51.5,4.8,,,,,,0")
        r._parse_sbs("MSG,4,1,1,CCCDDD,1,2024/01/01,12:00:00,2024/01/01,12:00:00,,,480.0,270.0,,,,,,,,0")
        flights = r.get_active_flights()
        assert all(f.is_complete() for f in flights)
        assert any(f.callsign == "EZY999" for f in flights)

    def test_stale_tracks_removed_by_get_active(self):
        r = self._reader()
        r._parse_sbs("MSG,1,1,1,STALE1,1,2024/01/01,12:00:00,2024/01/01,12:00:00,OLD100,,,,,,,,,,,0")
        r._tracks["STALE1"].updated_at = time.monotonic() - 120
        r.get_active_flights()
        assert "STALE1" not in r._tracks


# ── TelemetryEvent (Pydantic validation, OWASP A03) ───────────────────────────

VALID_ADSB = dict(
    message_type="ADSB_TELEMETRY",
    flight_id="BAW123",
    timestamp="2026-06-29T12:00:00+00:00",
    latitude=51.5,
    longitude=4.8,
    altitude_ft=35000,
    speed_knots=475,
)

VALID_VISION = {
    **{k: v for k, v in VALID_ADSB.items() if k != "message_type"},
    "message_type": "EDGE_VISION_AI",
    "camera_id": "PI-CAM-01",
    "contrail_detected": True,
    "confidence_score": 0.87,
}


class TestTelemetryValidation:
    def test_valid_adsb_passes(self):
        e = TelemetryEvent(**VALID_ADSB)
        assert e.flight_id == "BAW123"

    def test_valid_vision_passes(self):
        e = TelemetryEvent(**VALID_VISION)
        assert e.contrail_detected is True
        assert e.confidence_score == pytest.approx(0.87)

    # flight_id constraints
    def test_flight_id_too_short(self):
        with pytest.raises(ValidationError):
            TelemetryEvent(**{**VALID_ADSB, "flight_id": "AB"})

    def test_flight_id_too_long(self):
        with pytest.raises(ValidationError):
            TelemetryEvent(**{**VALID_ADSB, "flight_id": "A" * 13})

    def test_flight_id_invalid_chars(self):
        with pytest.raises(ValidationError):
            TelemetryEvent(**{**VALID_ADSB, "flight_id": "baw-123!"})

    def test_flight_id_lowercase_rejected(self):
        with pytest.raises(ValidationError):
            TelemetryEvent(**{**VALID_ADSB, "flight_id": "baw123"})

    # latitude / longitude
    def test_lat_above_90_rejected(self):
        with pytest.raises(ValidationError):
            TelemetryEvent(**{**VALID_ADSB, "latitude": 91.0})

    def test_lat_below_minus90_rejected(self):
        with pytest.raises(ValidationError):
            TelemetryEvent(**{**VALID_ADSB, "latitude": -91.0})

    def test_lon_above_180_rejected(self):
        with pytest.raises(ValidationError):
            TelemetryEvent(**{**VALID_ADSB, "longitude": 181.0})

    # altitude
    def test_altitude_above_60000_rejected(self):
        with pytest.raises(ValidationError):
            TelemetryEvent(**{**VALID_ADSB, "altitude_ft": 60001})

    def test_altitude_negative_rejected(self):
        with pytest.raises(ValidationError):
            TelemetryEvent(**{**VALID_ADSB, "altitude_ft": -1})

    # speed
    def test_speed_above_1000_rejected(self):
        with pytest.raises(ValidationError):
            TelemetryEvent(**{**VALID_ADSB, "speed_knots": 1001})

    # confidence_score
    def test_confidence_above_1_rejected(self):
        with pytest.raises(ValidationError):
            TelemetryEvent(**{**VALID_VISION, "confidence_score": 1.01})

    def test_confidence_negative_rejected(self):
        with pytest.raises(ValidationError):
            TelemetryEvent(**{**VALID_VISION, "confidence_score": -0.01})

    # heading (optional)
    def test_heading_none_allowed(self):
        e = TelemetryEvent(**{**VALID_ADSB, "heading": None})
        assert e.heading is None

    def test_heading_above_360_rejected(self):
        with pytest.raises(ValidationError):
            TelemetryEvent(**{**VALID_ADSB, "heading": 361.0})

    # camera_id (optional)
    def test_camera_id_none_for_adsb(self):
        e = TelemetryEvent(**VALID_ADSB)
        assert e.camera_id is None
