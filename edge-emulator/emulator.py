import time
import json
import random
import datetime
import os
from azure.eventhub import EventHubProducerClient, EventData

# get connection string from ENV 
CONNECTION_STR = os.getenv('CONN_STR')
EVENTHUB_NAME = "telemetry-adsb-inbound"

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

def main():
    # Client init
    producer = EventHubProducerClient.from_connection_string(conn_str=CONNECTION_STR, eventhub_name=EVENTHUB_NAME)
    
    print(f"Start emulator COAV Edge. Sending data to Event Hub: {EVENTHUB_NAME}...")
    
    try:
        with producer:
            while True:
                # Gen data pack
                data = generate_telemetry()
                json_data = json.dumps(data)
                
                # Create EventData object
                event_data_batch = producer.create_batch()
                event_data_batch.add(EventData(json_data))
                
                # Send to Event Hub
                producer.send_batch(event_data_batch)
                print(f" [x] Sent: {json_data}")
                
                # Wait 1 second between messages
                time.sleep(1)
    except KeyboardInterrupt:
        print("\nEmulator stopped.")

if __name__ == "__main__":
    main()