# Edge Capture Architecture

COAV — Contrail Avoidance · Raspberry Pi / ACI edge component

---

## What runs on the edge device

```
┌─────────────────────────────────────────────────────┐
│  Raspberry Pi 4 (or Azure ACI for cloud emulation)  │
│                                                     │
│  ┌──────────────┐    ┌──────────────────────────┐   │
│  │  Camera      │───▶│  Python capture.py       │   │
│  │  Module 3    │    │  1 FPS capture loop      │   │
│  │  or USB cam  │    │  └─▶ inference.py        │   │
│  └──────────────┘    │      ContrailDetector    │   │
│                      │      ONNX Runtime (CPU)  │   │
│  ┌──────────────┐    │      ResUNet-34           │   │
│  │  SDR dongle  │    └──────────┬───────────────┘   │
│  │  + dump1090  │               │ ADSB_TELEMETRY    │
│  │  SBS:30003   │───────────────┤ EDGE_VISION_AI    │
│  └──────────────┘               │                   │
└────────────────────────────────-│───────────────────┘
                                  ▼
                         Azure Event Hub
                     telemetry-adsb-inbound
                                  │
                                  ▼
                         Spring Boot backend
                        FlightStateStore
                        alertStatus enrichment
```

---

## Two implementations

| | `python/capture.py` | `node/capture.js` |
|---|---|---|
| **Camera** | picamera2 (Pi Camera Module 3) or OpenCV | V4L2 USB webcam via node-v4l2camera |
| **ADS-B** | TCP socket → dump1090 SBS parser | TCP socket → dump1090 SBS parser |
| **Inference** | In-process (ONNX Runtime) | Subprocess call to `inference.py` |
| **Event Hub SDK** | `azure-eventhub` (Python) | `@azure/event-hubs` (Node.js) |
| **Validation** | Pydantic (OWASP A03) | Manual regex check |
| **Recommended for** | Primary: best inference integration | Demonstrating Node.js capability |

Node.js delegates inference to Python via `child_process.execFile` — the ML model stays in Python/ONNX while the camera I/O and Event Hub plumbing run in Node.

---

## Contrail detection model

**Architecture:** ResUNet-34 (ResNet-34 encoder + U-Net decoder)

**Training data:**
1. Pre-training: ImageNet (ResNet-34 encoder weights via `segmentation_models_pytorch`)
2. Fine-tuning: **GVCCS** (Ground Visible Camera Contrail Sequences)
   - Source: **EUROCONTROL MUAC**, Brétigny-sur-Orge, France
   - 122 video sequences, 24,228 frames at 1024×1024 px
   - Instance-level polygon annotations with temporal tracking
   - Zenodo: https://zenodo.org/records/15743988

**Why GVCCS:**  
This is the same operational environment as the target deployment (MUAC).
Ground-camera images differ significantly from satellite imagery (GOES-16) —
perspective, lighting, cloud background — so using MUAC's own dataset
avoids domain shift and demonstrates domain-specific fine-tuning.

**Inference pipeline:**
```
Raw frame (BGR, any resolution)
    │
    ▼
Preprocess: resize → 512×512, ImageNet normalisation → (1, 3, 512, 512) float32
    │
    ▼
ONNX Runtime: ResUNet-34 forward pass (~60 ms on Pi 4 CPU)
    │
    ▼
Sigmoid → binary mask (threshold: 0.45)
    │
    ▼
Upsample mask back to original resolution
    │
    ▼
DetectionResult: {contrail_detected, confidence, pixel_ratio, mask}
```

---

## Why inference runs in the cloud (production cost model)

At 1 FPS / 40 cameras:

| Option | Cost | Latency | Notes |
|---|---|---|---|
| Edge-only (ONNX on Pi) | ~$0 compute | 60 ms | Low resolution, no GPU |
| Cloud GPU VM (NC6s_v3) | ~$0.50/hr | <10 ms | Full resolution, batched |
| Vision API (Anthropic/Azure) | ~$288/hr | 200 ms | Per-image pricing, rate limited |

**Chosen architecture:** Edge pre-filter (MobileNet binary: contrail/no-contrail) drops
~70% of empty-sky frames before upload; cloud GPU VM runs full ResUNet segmentation
on the remaining frames. This gives accuracy + cost efficiency.

For the PoC, the Pi runs the full ResUNet-34 at 1 FPS (acceptable for demonstration).

---

## Getting started

```bash
# Python path
cd edge-pi/python
pip install -r requirements.txt

# Download pre-trained weights (contrail-seg ResUNet-34)
python inference.py --download onnx

# Test on a single image
python inference.py /path/to/sky_image.jpg --show

# Fine-tune on GVCCS (after downloading from Zenodo)
python train.py --data /path/to/gvccs --epochs 20

# Export to ONNX for Pi deployment
python inference.py --export-onnx

# Run full capture loop (requires dump1090 + camera)
CONN_STR="..." python capture.py

# Node.js path
cd edge-pi/node
npm install
CONN_STR="..." node capture.js
```
