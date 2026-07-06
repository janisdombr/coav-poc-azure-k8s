FROM python:3.12-slim

WORKDIR /app

# Unbuffered stdout/stderr so `az container logs` streams output in real time.
# Without this, Python block-buffers stdout in a container and logs look empty
# even while the process is running — which blinds startup/hang diagnosis.
ENV PYTHONUNBUFFERED=1

# libglib2.0-0 is required by opencv-python-headless at import time
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY emulator.py .

# Held-out GVCCS val frames for the camera channel (Day 11 / P1).
# Generate BEFORE docker build:  python prepare_val_frames.py
# If the directory is empty the emulator falls back to synthetic frames.
COPY frames/ ./frames/

# Optional real U-Net inference: mount edge-pi/python (+ weights) and set
# INFERENCE_DIR=/inference — otherwise the OpenCV heuristic fallback is used.

# CONN_STR must be provided at runtime via environment variable
ENV CONN_STR=""

USER 10001

CMD ["python", "emulator.py"]
