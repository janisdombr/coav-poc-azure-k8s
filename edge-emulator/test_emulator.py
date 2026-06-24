import pytest
from pydantic import ValidationError
from emulator import ADSBTelemetry, generate_telemetry_dict

def test_valid_telemetry_generation():
    """Test: The generated data must strictly comply with the schema"""
    raw = generate_telemetry_dict()
    instance = ADSBTelemetry(**raw)
    assert instance.flight_id == "COAV-882"
    assert 28000 <= instance.altitude_ft <= 35000

def test_invalid_latitude_overflow():
    """Security Test: Malformed latitude (>90) should be rejected (OWASP: Injection/Parametric Attack Protection)"""
    bad_data = {
        "flight_id": "COAV-882",
        "timestamp": "2026-06-24T12:00:00Z",
        "latitude": 95.0,  # Error is here
        "longitude": 17.98,
        "altitude_ft": 30000,
        "speed_knots": 450
    }
    with pytest.raises(ValidationError):
        ADSBTelemetry(**bad_data)

def test_flight_id_regex_injection():
    """Security Test: Attempts to insert special characters into the Board Identifier should be prevented"""
    bad_data = {
        "flight_id": "COAV;DROP",  # Attempted SQL/Command injection via string
        "timestamp": "2026-06-24T12:00:00Z",
        "latitude": 69.23,
        "longitude": 17.98,
        "altitude_ft": 30000,
        "speed_knots": 450
    }
    with pytest.raises(ValidationError):
        ADSBTelemetry(**bad_data)