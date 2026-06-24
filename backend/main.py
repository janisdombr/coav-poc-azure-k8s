import os
import sys
import json
from pydantic import BaseModel, Field, ValidationError
from azure.eventhub import EventHubConsumerClient

# Strict type validation on the K8s receiver side (OWASP A03:2021-Injection)
class IncomingTelemetry(BaseModel):
    flight_id: str = Field(..., pattern=r"^[A-Z0-9\-]+$")
    timestamp: str
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    altitude_ft: int = Field(..., ge=0, le=60000)
    speed_knots: int = Field(..., ge=0, le=1000)

def simulate_databricks_enrichment(flight_id: str, altitude: int):
    """
    [PLUG FOR: DATABRICKS & PYSPARK]
    In a production system this is where the Delta Lake/Unity Catalog cache is requesting
    where historical weather data processed by Spark scripts and contrail risk zones are stored
    """
    # Mock the logic: at altitudes above 31,000 feet (FL310), the risk of wake formation is critical
    is_contrail_risk = altitude > 31000
    return {
        "enriched_by": "Databricks_PySpark_Engine_v1",
        "contrail_formation_risk": "HIGH" if is_contrail_risk else "LOW",
        "atmospheric_humidity_threshold": "CRITICAL" if is_contrail_risk else "NORMAL"
    }

def on_event(partition_context, event):
    """Callback function when a packet is received from Azure Event Hub"""
    raw_payload = event.body_as_str(encoding='UTF-8')
    
    try:
        
        data_dict = json.loads(raw_payload)
        telemetry = IncomingTelemetry(**data_dict)
        
        # Mock for sending to Frontend
        print(f"\n[HOT PATH] Live stream for Vue map -> Flight: {telemetry.flight_id} | Alt: {telemetry.altitude_ft}ft")
        
        # Mock for analytics
        analytics = simulate_databricks_enrichment(telemetry.flight_id, telemetry.altitude_ft)
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