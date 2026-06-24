import time
import json
import random
import datetime
import os
from typing import Literal
from pydantic import BaseModel, Field, ValidationError
from azure.eventhub import EventHubProducerClient, EventData

# Strict data schema for ATM/COAV telemetry (protetion from not valid types or onjections)
class ADSBTelemetry(BaseModel):
    flight_id: str = Field(..., min_length=3, max_length=10, pattern=r"^[A-Z0-9\-]+$")
    timestamp: str
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    altitude_ft: int = Field(..., ge=0, le=60000)
    speed_knots: int = Field(..., ge=0, le=1000)

def generate_telemetry():
    """Generate mock data from airplane telemetry (ADSB)"""
    # Base point under Norway (Finnsnes/Tromsø)
    lat = 69.23 + random.uniform(-0.05, 0.05)
    lon = 17.98 + random.uniform(-0.05, 0.05)
    # Altitude in feet (FL280 to FL350)
    altitude = random.randint(28000, 35000)
    
    payload = {
        "flight_id": "COAV-882",
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "latitude": round(lat, 5),
        "longitude": round(lon, 5),
        "altitude_ft": altitude,
        "speed_knots": random.randint(400, 480)
    }
    return payload
def generate_telemetry_dict() -> dict:
    """Generate mock data from airplane telemetry (ADSB)"""
    # Base point under Norway (Finnsnes/Tromsø)
    lat = 69.23 + random.uniform(-0.05, 0.05)
    lon = 17.98 + random.uniform(-0.05, 0.05)
    # Altitude in feet (FL280 to FL350)
    altitude = random.randint(28000, 35000)
    return {
        "flight_id": "COAV-882",
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "latitude": round(lat, 5),
        "longitude": round(lon, 5),
        "altitude_ft": altitude,
        "speed_knots": random.randint(400, 480)
    }

def main():
    # get connection string from ENV 
    CONNECTION_STR = os.getenv('CONN_STR')
    if not CONNECTION_STR:
        print("Error: Environment variable 'CONN_STR' is not set.")
        return
    EVENTHUB_NAME = "telemetry-adsb-inbound"
    # Client init
    producer = EventHubProducerClient.from_connection_string(conn_str=CONNECTION_STR, eventhub_name=EVENTHUB_NAME)
    
    print(f"Start emulator COAV Edge. Sending data to Event Hub: {EVENTHUB_NAME}...")
    
    try:
        with producer:
            while True:
                # Gen data pack
                raw_data = generate_telemetry_dict()
                try:
                    # Validation of data before send to hub
                    telemetry = ADSBTelemetry(**raw_data)
                    json_data = telemetry.model_dump_json()
                
                    # Create EventData object
                    event_data_batch = producer.create_batch()
                    event_data_batch.add(EventData(json_data))
                
                    # Send to Event Hub
                    producer.send_batch(event_data_batch)
                    print(f" [x] Sent: {json_data}")
                except ValidationError as ve:
                    print(f" [OWASP ALERT] Data has been not passed security validation: {ve}")
                # Wait 1 second between messages
                time.sleep(1)
    except KeyboardInterrupt:
        print("\nEmulator stopped.")

if __name__ == "__main__":
    main()