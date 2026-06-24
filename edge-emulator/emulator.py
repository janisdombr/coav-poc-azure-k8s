import time
import json
import random
import datetime
import os
import math
from typing import Literal
from pydantic import BaseModel, Field, ValidationError
from azure.eventhub import EventHubProducerClient, EventData

# Strict data schema for ATM/COAV telemetry (protection from not valid types or injections)
class ADSBTelemetry(BaseModel):
    message_type: Literal["ADSB_TELEMETRY", "EDGE_VISION_AI"]
    flight_id: str = Field(..., min_length=3, max_length=12, pattern=r"^[A-Z0-9\-]+$")
    timestamp: str
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    altitude_ft: int = Field(..., ge=0, le=60000)
    speed_knots: int = Field(..., ge=0, le=1000)
    camera_id: str | None = Field(None, min_length=3, max_length=20)
    contrail_detected: bool | None = None
    confidence_score: float | None = Field(None, ge=0.0, le=1.0)

# Local 3D critical weather zones cache (ISSR regions)
CRITICAL_ZONES = [
    (69.1000, 69.3500, 17.8000, 18.2000, 31000, 36000), # Zone Alpha near radar station
    (69.4000, 69.6500, 18.3000, 18.7000, 33000, 39000)  # Zone Bravo northeast
]

def is_inside_critical_zone(lat: float, lon: float, alt: int) -> bool:
    """Check if the aircraft coordinates intersect with 3D weather cubes"""
    for zone in CRITICAL_ZONES:
        min_lat, max_lat, min_lon, max_lon, min_alt, max_alt = zone
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon and min_alt <= alt <= max_alt:
            return True
    return False

def generate_airspace_traffic_payloads() -> list[dict]:
    """Generate mock data bundle for multiple aircraft based on current time functions"""
    t = time.time()
    iso_timestamp = datetime.datetime.utcnow().isoformat() + "Z"
    payloads = []
    
    # Base coordination matrix for Northern Norway sector
    base_lat, base_lon = 69.23, 17.98
    
    # Dynamic time-based flight scheduling (5-minute interval windows)
    window_id = int((t % 86400) / 300)
    flights_pool = [
        {"id": f"C{(window_id * 3 + 1) % 900 + 100}-CLB", "type": "CLIMB"},
        {"id": f"C{(window_id * 3 + 2) % 900 + 100}-CRZ", "type": "CRUISE"},
        {"id": f"C{(window_id * 3 + 3) % 900 + 100}-DST", "type": "DISTANT"}
    ]
    
    for f_info in flights_pool:
        fid = f_info["id"]
        ftype = f_info["type"]
        
        if ftype == "CLIMB":
            # Aircraft taking off and climbing
            elapsed = (t % 300) / 10.0
            lat = base_lat + (elapsed * 0.002)
            lon = base_lon + (elapsed * 0.003)
            alt = min(12000 + int(elapsed * 800), 32000)
            speed = min(250 + int(elapsed * 10), 410)
            cam_visible = True
            
        elif ftype == "CRUISE":
            # Aircraft cruising on high altitude flight level
            angle = (t % 360) * (math.pi / 180)
            lat = base_lat + (0.04 * math.sin(angle))
            lon = base_lon + (0.04 * math.cos(angle))
            alt = 34000
            speed = 450
            cam_visible = True
            
        else:
            # Distant high-altitude transit aircraft, passing quickly out of camera range
            elapsed = (t % 300) / 5.0
            lat = base_lat + 0.15 + (elapsed * 0.005)
            lon = base_lon + 0.15 + (elapsed * 0.005)
            alt = 37000
            speed = 470
            cam_visible = False
            
        # 1. Append ADS-B Telemetry message layout
        payloads.append({
            "message_type": "ADSB_TELEMETRY",
            "flight_id": fid,
            "timestamp": iso_timestamp,
            "latitude": round(lat, 5),
            "longitude": round(lon, 5),
            "altitude_ft": alt,
            "speed_knots": speed
        })
        
        # 2. Append Edge Vision AI message layout if visible by optical ground station
        if cam_visible:
            has_contrail = is_inside_critical_zone(lat, lon, alt)
            payloads.append({
                "message_type": "EDGE_VISION_AI",
                "camera_id": "STATION-FN-04",
                "flight_id": fid,
                "timestamp": iso_timestamp,
                "latitude": round(lat, 5),
                "longitude": round(lon, 5),
                "altitude_ft": alt,
                "speed_knots": speed,
                "contrail_detected": has_contrail,
                "confidence_score": round(0.91 + (0.05 * math.sin(t)), 2) if has_contrail else 0.95
            })
            
    return payloads

def main():
    # get connection string from ENV 
    CONNECTION_STR = os.getenv('CONN_STR')
    if not CONNECTION_STR:
        print("Error: Environment variable 'CONN_STR' is not set.")
        return
    EVENTHUB_NAME = "telemetry-adsb-inbound"
    
    # Client init
    producer = EventHubProducerClient.from_connection_string(conn_str=CONNECTION_STR, eventhub_name=EVENTHUB_NAME)
    print(f"Start emulator COAV Edge. Sending dynamic multi-flight streams to Event Hub: {EVENTHUB_NAME}...")
    
    try:
        with producer:
            while True:
                # Gen dynamic data pack list
                raw_payloads = generate_airspace_traffic_payloads()
                
                try:
                    event_data_batch = producer.create_batch()
                    
                    for raw_data in raw_payloads:
                        # Validation of data before send to hub
                        telemetry = ADSBTelemetry(**raw_data)
                        json_data = telemetry.model_dump_json()
                        event_data_batch.add(EventData(json_data))
                        print(f" [x] Sent [{raw_data['message_type']}]: {json_data}")
                    
                    # Send batch to Event Hub
                    producer.send_batch(event_data_batch)
                    
                except ValidationError as ve:
                    print(f" [OWASP ALERT] Data has been not passed security validation: {ve}")
                    
                # Wait 3 seconds between messages
                time.sleep(3)
    except KeyboardInterrupt:
        print("\nEmulator stopped.")

if __name__ == "__main__":
    main()