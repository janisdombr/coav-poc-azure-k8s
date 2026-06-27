import os
import sys
import json
from typing import Literal
from pydantic import BaseModel, Field, ValidationError
from azure.eventhub import EventHubConsumerClient

# Dynamic storage for tracked active flight states in memory
FLIGHT_STATE = {}

# Local cache of 3D critical weather zones received from the predictive ML model
WEATHER_GRID_ISSR = [
    {"min_lat": 50.20, "max_lat": 51.00, "min_lon": 3.80, "max_lon": 5.40, "min_alt": 33000, "max_alt": 38000},
    {"min_lat": 51.30, "max_lat": 52.50, "min_lon": 5.80, "max_lon": 8.20, "min_alt": 31000, "max_alt": 37000},
]

# Strict type validation on the K8s receiver side (OWASP A03:2021-Injection)
class IncomingTelemetry(BaseModel):
    message_type: Literal["ADSB_TELEMETRY", "EDGE_VISION_AI"]
    flight_id: str = Field(..., pattern=r"^[A-Z0-9\-]+$")
    timestamp: str
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    altitude_ft: int = Field(..., ge=0, le=60000)
    speed_knots: int = Field(..., ge=0, le=1000)
    camera_id: str | None = Field(None)
    contrail_detected: bool | None = None
    confidence_score: float | None = Field(None, ge=0.0, le=1.0)

def check_weather_cache_issr(lat: float, lon: float, alt: int) -> bool:
    """Correlate flight position with 3D weather grid array cubes"""
    for cube in WEATHER_GRID_ISSR:
        if cube["min_lat"] <= lat <= cube["max_lat"] and cube["min_lon"] <= lon <= cube["max_lon"]:
            if cube["min_alt"] <= alt <= cube["max_alt"]:
                return True
    return False

def evaluate_stream_join(flight_id: str):
    """Processes joined events from multiple streams and evaluates tactical decisions"""
    state = FLIGHT_STATE.get(flight_id)
    if not state or not state["telemetry"] or state["ai_detection"] is None:
        return
        
    tel = state["telemetry"]
    ai = state["ai_detection"]
    
    lat, lon, alt = tel.latitude, tel.longitude, tel.altitude_ft
    is_issr_zone = check_weather_cache_issr(lat, lon, alt)
    
    print(f"\n[HOT PATH] Stream Evaluation -> Flight: {flight_id} | Pos: {lat}, {lon} | Alt: {alt}ft")
    print(f"[EDGE AI VERIFICATION] Observed Contrail: {ai.contrail_detected} (Conf: {ai.confidence_score})")
    print(f"[MET OFFICE 3D CACHE] ISSR Status: {is_issr_zone}")
    
    # Core ATM routing tactical business logic
    if ai.contrail_detected and is_issr_zone:
        print(f"🔴 [CRITICAL ALERT] Persistent cirrus formation verified for {flight_id}! Instruction: Change Flight Level.")
    elif ai.contrail_detected and not is_issr_zone:
        print(f"       Notice: Non-persistent contrail observed for {flight_id}. Short lifecycle. No action.")
    else:
        print(f"       Clean Sky: No contrail formation detected for {flight_id}.")

def simulate_databricks_enrichment(flight_id: str, altitude: int, is_issr: bool):
    """
    [PLUG FOR: DATABRICKS & PYSPARK]
    In a production system this is where the Delta Lake/Unity Catalog cache is requesting
    where historical weather data processed by Spark scripts and contrail risk zones are stored
    """
    return {
        "enriched_by": "Databricks_PySpark_Engine_v1",
        "contrail_formation_risk": "HIGH" if is_issr else "LOW",
        "atmospheric_humidity_threshold": "CRITICAL" if is_issr else "NORMAL"
    }

def on_event(partition_context, event):
    """Callback function when a packet is received from Azure Event Hub"""
    raw_payload = event.body_as_str(encoding='UTF-8')
    
    try:
        data_dict = json.loads(raw_payload)
        telemetry = IncomingTelemetry(**data_dict)
        fid = telemetry.flight_id
        
        # Initialize flight track storage dynamically if encountered for the first time
        if fid not in FLIGHT_STATE:
            FLIGHT_STATE[fid] = {"telemetry": None, "ai_detection": None}
            print(f"[STATE] Dynamic entry initialized for new flight path: {fid}")
            
        if telemetry.message_type == "ADSB_TELEMETRY":
            FLIGHT_STATE[fid]["telemetry"] = telemetry
        elif telemetry.message_type == "EDGE_VISION_AI":
            FLIGHT_STATE[fid]["ai_detection"] = telemetry
            # Try to match streams and verify state, trigger evaluation only when the full window/pair is complete
            evaluate_stream_join(fid)
        
        # Cold path integration reporting
        is_issr = check_weather_cache_issr(telemetry.latitude, telemetry.longitude, telemetry.altitude_ft)
        analytics = simulate_databricks_enrichment(fid, telemetry.altitude_ft, is_issr)
        print(f"[COLD PATH INTEGRATION] {analytics}")
        
    except (json.JSONDecodeError, ValidationError) as err:
        print(f"[SECURITY ALERT][OWASP A03] Malicious or broken package rejected: {err}")
    
    # checkpoint message
    partition_context.update_checkpoint(event)

def main():
    CONNECTION_STR = os.getenv("CONN_STR")
    CONSUMER_GROUP = "$Default"
    if not CONNECTION_STR:
        print("CRITICAL: Environment variable 'CONN_STR' is missing!")
        sys.exit(1)
    client = EventHubConsumerClient.from_connection_string(
        conn_str=CONNECTION_STR,
        consumer_group=CONSUMER_GROUP
    )
    print("COAV K8s Backend launched successfully. Waiting for telemetry stream from Azure...")
    with client:
        # reading new messages from hub starting from launch app
        client.receive(on_event=on_event, starting_position="-1")

if __name__ == "__main__":
    main()