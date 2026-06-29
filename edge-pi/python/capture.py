"""
COAV Edge Capture — Raspberry Pi / ACI
Captures frames at 1 FPS, runs contrail inference, reads ADS-B from dump1090,
then sends paired telemetry events to Azure Event Hub.

Event types sent (mirrors emulator.py schema):
  ADSB_TELEMETRY  — position + flight level from dump1090 SBS feed
  EDGE_VISION_AI  — contrail detection result from inference.py

Tested on:
  Raspberry Pi 4 + Camera Module 3 (picamera2)
  Raspberry Pi 4 + USB webcam (OpenCV VideoCapture)

Install: pip install -r requirements.txt
Run:     CONN_STR="<event_hub_conn_str>" python capture.py
"""

import datetime
import json
import logging
import os
import socket
import sys
import threading
import time
from typing import Optional

import cv2
import numpy as np
from azure.eventhub import EventData, EventHubProducerClient
from pydantic import BaseModel, Field, ValidationError

from inference import ContrailDetector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
EVENTHUB_NAME  = "telemetry-adsb-inbound"
CAMERA_ID      = os.environ.get("CAMERA_ID", "PI-CAM-01")
CAPTURE_FPS    = 1                                 # 1 frame/sec — matches emulator cadence
DUMP1090_HOST  = os.environ.get("DUMP1090_HOST", "127.0.0.1")
DUMP1090_PORT  = int(os.environ.get("DUMP1090_PORT", "30003"))   # SBS BaseStation port


# ── Telemetry schema (OWASP A03:2021 — validates before sending) ───────────────
class TelemetryEvent(BaseModel):
    message_type: str
    camera_id: Optional[str]   = None
    flight_id: str             = Field(..., min_length=3, max_length=12,
                                       pattern=r"^[A-Z0-9\-]+$")
    timestamp: str
    latitude: float            = Field(..., ge=-90.0, le=90.0)
    longitude: float           = Field(..., ge=-180.0, le=180.0)
    altitude_ft: int           = Field(..., ge=0, le=60000)
    speed_knots: int           = Field(..., ge=0, le=1000)
    heading: Optional[float]   = Field(None, ge=0.0, le=360.0)
    contrail_detected: Optional[bool]  = None
    confidence_score: Optional[float]  = Field(None, ge=0.0, le=1.0)


# ── ADS-B reader (dump1090 SBS BaseStation format) ────────────────────────────

class AdsbTrack:
    """Accumulates SBS messages for one ICAO hex code into a usable Flight record."""

    def __init__(self, icao: str):
        self.icao       = icao
        self.callsign   : Optional[str]   = None
        self.lat        : Optional[float] = None
        self.lon        : Optional[float] = None
        self.altitude   : Optional[int]   = None
        self.speed      : Optional[int]   = None
        self.heading    : Optional[float] = None
        self.updated_at : float           = time.monotonic()

    def is_complete(self) -> bool:
        return all([self.callsign, self.lat is not None,
                    self.lon is not None, self.altitude is not None])

    def stale(self, max_age_s: float = 60.0) -> bool:
        return (time.monotonic() - self.updated_at) > max_age_s


class Dump1090Reader(threading.Thread):
    """
    Reads the SBS (BaseStation) TCP stream from dump1090 on port 30003.
    Each MSG type 1/3/4 updates the shared track dictionary.
    """

    def __init__(self):
        super().__init__(daemon=True)
        self._tracks: dict[str, AdsbTrack] = {}
        self._lock = threading.Lock()

    def run(self) -> None:
        while True:
            try:
                self._connect_and_read()
            except Exception as exc:
                logger.warning("dump1090 disconnected: %s — retrying in 5 s", exc)
                time.sleep(5)

    def _connect_and_read(self) -> None:
        with socket.create_connection((DUMP1090_HOST, DUMP1090_PORT), timeout=10) as sock:
            logger.info("Connected to dump1090 at %s:%d", DUMP1090_HOST, DUMP1090_PORT)
            buf = ""
            while True:
                chunk = sock.recv(4096).decode("ascii", errors="ignore")
                if not chunk:
                    break
                buf += chunk
                *lines, buf = buf.split("\n")
                for line in lines:
                    self._parse_sbs(line.strip())

    def _parse_sbs(self, line: str) -> None:
        # SBS format: MSG,<msgType>,<sessionID>,<aircraftID>,<hexIdent>,...
        parts = line.split(",")
        if len(parts) < 22 or parts[0] != "MSG":
            return
        icao     = parts[4].strip().upper()
        msg_type = parts[1].strip()

        with self._lock:
            track = self._tracks.setdefault(icao, AdsbTrack(icao))
            track.updated_at = time.monotonic()

            if msg_type == "1":                    # callsign identification
                cs = parts[10].strip()
                if cs:
                    track.callsign = cs
            elif msg_type == "3":                  # airborne position
                try:
                    track.altitude = int(parts[11]) if parts[11] else track.altitude
                    track.lat      = float(parts[14]) if parts[14] else track.lat
                    track.lon      = float(parts[15]) if parts[15] else track.lon
                except ValueError:
                    pass
            elif msg_type == "4":                  # airborne velocity
                try:
                    track.speed   = int(float(parts[12])) if parts[12] else track.speed
                    track.heading = float(parts[13])       if parts[13] else track.heading
                except ValueError:
                    pass

    def get_active_flights(self) -> list[AdsbTrack]:
        with self._lock:
            stale = [k for k, v in self._tracks.items() if v.stale()]
            for k in stale:
                del self._tracks[k]
            return [t for t in self._tracks.values() if t.is_complete()]


# ── Camera capture ─────────────────────────────────────────────────────────────

def open_camera() -> cv2.VideoCapture:
    """Opens picamera2 (Pi Camera Module 3) or first available USB webcam."""
    try:
        from picamera2 import Picamera2          # type: ignore
        picam = Picamera2()
        picam.configure(picam.create_preview_configuration(
            main={"format": "BGR888", "size": (1920, 1080)}
        ))
        picam.start()
        logger.info("Camera: picamera2 (Pi Camera Module 3)")
        return picam                             # duck-typed: has .capture_array()
    except (ImportError, RuntimeError):
        pass

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise RuntimeError("No camera found — check USB webcam or Pi Camera connection")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    logger.info("Camera: USB webcam via OpenCV")
    return cap


def capture_frame(camera) -> Optional[np.ndarray]:
    """Returns BGR frame from either picamera2 or cv2.VideoCapture."""
    try:
        if hasattr(camera, "capture_array"):     # picamera2
            return camera.capture_array("main")  # already BGR
        ret, frame = camera.read()
        return frame if ret else None
    except Exception as exc:
        logger.error("Frame capture failed: %s", exc)
        return None


# ── Main loop ──────────────────────────────────────────────────────────────────

def main() -> None:
    conn_str = os.environ.get("CONN_STR")
    if not conn_str:
        raise RuntimeError("CONN_STR environment variable is required")

    detector = ContrailDetector()
    adsb     = Dump1090Reader()
    adsb.start()

    camera = open_camera()
    producer = EventHubProducerClient.from_connection_string(
        conn_str=conn_str, eventhub_name=EVENTHUB_NAME
    )

    logger.info("COAV Edge Capture started (camera=%s, 1 FPS)", CAMERA_ID)

    try:
        with producer:
            while True:
                loop_start = time.monotonic()

                frame = capture_frame(camera)
                if frame is None:
                    logger.warning("Skipping empty frame")
                    time.sleep(1)
                    continue

                # Run contrail inference
                detection = detector.detect(frame)
                iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

                # Build one event pair per active ADS-B track
                flights = adsb.get_active_flights()
                if not flights:
                    logger.debug("No ADS-B tracks — waiting for dump1090 data")

                events: list[dict] = []
                for track in flights:
                    base = dict(
                        flight_id   = track.callsign,
                        timestamp   = iso,
                        latitude    = round(track.lat, 5),
                        longitude   = round(track.lon, 5),
                        altitude_ft = track.altitude,
                        speed_knots = track.speed or 0,
                        heading     = round(track.heading, 1) if track.heading else None,
                    )
                    events.append(dict(message_type="ADSB_TELEMETRY", **base))
                    events.append(dict(
                        message_type      = "EDGE_VISION_AI",
                        camera_id         = CAMERA_ID,
                        contrail_detected = detection.contrail_detected,
                        confidence_score  = detection.confidence,
                        **base,
                    ))

                # Validate + send
                batch = producer.create_batch()
                for raw in events:
                    try:
                        validated = TelemetryEvent(**raw)
                        batch.add(EventData(validated.model_dump_json()))
                    except ValidationError as ve:
                        logger.error("Validation error (OWASP A03): %s", ve)

                if len(batch) > 0:
                    producer.send_batch(batch)

                logger.info(
                    "tick: contrail=%s conf=%.2f flights=%d events=%d backend=%s",
                    detection.contrail_detected, detection.confidence,
                    len(flights), len(events), detection.backend
                )

                # Maintain 1 FPS
                elapsed = time.monotonic() - loop_start
                time.sleep(max(0.0, 1.0 / CAPTURE_FPS - elapsed))

    except KeyboardInterrupt:
        logger.info("Stopped by user")
    finally:
        if hasattr(camera, "stop"):
            camera.stop()
        elif hasattr(camera, "release"):
            camera.release()


if __name__ == "__main__":
    main()
