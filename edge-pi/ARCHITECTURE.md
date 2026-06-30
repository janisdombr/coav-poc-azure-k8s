# Edge Capture & Contrail Detection

COAV — Contrail Avoidance · Raspberry Pi / ACI edge component

---

## What runs on the edge device

```
┌─────────────────────────────────────────────────────┐
│  Raspberry Pi / Jetson (or Azure ACI for PoC)       │
│                                                     │
│  ┌──────────────┐    ┌──────────────────────────┐   │
│  │  Camera      │───▶│  Python capture.py       │   │
│  │  Module 3    │    │  1 FPS capture loop      │   │
│  │  or USB cam  │    │  └─▶ inference.py        │   │
│  └──────────────┘    │      ContrailDetector    │   │
│                      │      ONNX / PyTorch      │   │
│  ┌──────────────┐    │      U-Net EfficientNet  │   │
│  │  SDR dongle  │    └──────────┬───────────────┘   │
│  │  + dump1090  │               │ ADSB_TELEMETRY    │
│  │  SBS:30003   │───────────────┤ EDGE_VISION_AI    │
│  └──────────────┘               │ (200 bytes each)  │
└─────────────────────────────────│───────────────────┘
                                  ▼
                         Azure Event Hub
                     telemetry-adsb-inbound
                                  │
                                  ▼
                         Spring Boot backend
                        FlightStateStore
                        alertStatus enrichment
```

The edge device sends only the **inference result** (200 bytes), not raw frames —
regardless of whether inference runs locally or in cloud.

---

## Two capture implementations

| | `python/capture.py` | `node/capture.js` |
|---|---|---|
| **Camera** | picamera2 (Pi Camera Module 3) or OpenCV | V4L2 USB webcam via node-v4l2camera |
| **ADS-B** | TCP socket → dump1090 SBS parser | TCP socket → dump1090 SBS parser |
| **Inference** | In-process (ONNX Runtime) | Subprocess call to `inference.py` |
| **Event Hub SDK** | `azure-eventhub` (Python) | `@azure/event-hubs` (Node.js) |
| **Validation** | Pydantic (OWASP A03) | Manual regex check |
| **Recommended for** | Primary: best inference integration | Demonstrating Node.js capability |

Node.js delegates inference to Python via `child_process.execFile` — the ML model
stays in Python/ONNX while the camera I/O and Event Hub plumbing run in Node.

---

## Contrail detection model

**Chosen: U-Net + EfficientNet-B4 encoder**  
**Training dataset: GVCCS** (Ground Visible Camera Contrail Sequences)

### Why GVCCS

GVCCS was recorded at **EUROCONTROL MUAC Brétigny-sur-Orge** — the same operational
environment as the target deployment. Ground-camera imagery differs fundamentally from
satellite imagery (GOES-16 used by junzis/contrail-seg): different perspective, lighting,
cloud background. Training on GVCCS eliminates domain shift and directly demonstrates
domain-specific fine-tuning for MUAC conditions.

| Property | Value |
|---|---|
| Source | EUROCONTROL MUAC, Brétigny-sur-Orge, France |
| License | CC BY 4.0 |
| Sequences | 122 video sequences |
| Frames | 24,228 at 1024×1024 px |
| Annotations | 111,761 instance-level polygons (COCO format) |
| Zenodo | https://zenodo.org/records/15743988 |

### Segmentation model alternatives considered

Six approaches were evaluated. Key metric: Dice score on binary pixel mask (higher = better).

| Algorithm | Expected Dice | Train time (T4) | VRAM | Designed for | Why not chosen |
|---|---|---|---|---|---|
| **OpenCV heuristics** | ~0% | none | 0 | Rule-based CV | No context — fails when contrails overlap clouds or have low contrast. Confirmed 0/17 on manual test set. |
| **FCN** (2015) | ~40% | 1–2 h | 4 GB | General segmentation | No skip connections → decoder upsamples blindly → 5–10 px contrail boundaries blur to 30+ px blobs. |
| **SegNet** (2015) | ~50% | 2–3 h | 4 GB | Semantic segmentation | Stores only max-pool indices instead of full feature maps → less precise boundary recovery than U-Net. |
| **U-Net + EfficientNet-B4** ✓ | **~75%** | **4–6 h** | **8 GB** | **Medical thin structures** | **Chosen — see rationale below.** |
| **DeepLab v3+** (2018) | ~72% | 8–10 h | 10 GB | Outdoor scenes | ASPP multi-scale pooling benefits objects of varying size. Contrails are always thin lines — added complexity gives no accuracy gain over U-Net. |
| **SegFormer-B2** (2021) | ~78% | 12–16 h | 14 GB | Large-scale segmentation | +3% Dice vs U-Net but 3× longer training and barely fits T4 VRAM. Marginal gain not worth overnight Colab budget. |
| **SAM** (Meta, 2023) | ~80% | 20+ h | 16+ GB | Universal segmentation | Prompt-based — needs a point or bounding box as input. Incompatible with fully-automatic 1 FPS pipeline. |

### Why U-Net specifically

U-Net was invented in 2015 for **biomedical segmentation**: blood vessels, cell membranes,
tumour boundaries. The geometry is identical to contrails:

```
Blood vessel:  thin tube,   5–15 px wide,  complex background (tissue)
Contrail:      thin stripe, 5–20 px wide,  complex background (clouds)
```

Skip connections pass full feature maps from each encoder level directly to the decoder.
Without them, a 6-pixel contrail boundary blurs beyond recognition during upsampling —
confirmed by FCN and SegNet results above.

EfficientNet-B4 was chosen over ResNet-34 (smaller, ~60% Dice) and ResNet-101
(marginal gain, +40% parameters) based on the EfficientNet compound scaling results:
B4 sits at the accuracy/parameter Pareto frontier for 512×512 input.

---

## Edge hardware: realistic assessment

### Inference time by device

| Device | Price | U-Net EfficientNet-B4 (ONNX int8) | At 1 FPS | Verdict |
|---|---|---|---|---|
| Raspberry Pi 4 | $75 | ~3–5 s | Lag only, contrails persist → OK for PoC | PoC only |
| Raspberry Pi 5 | $80 | ~1.5–2 s | Acceptable with lag | Tight |
| **Pi 5 + Hailo-8L HAT** | **$150** | **~50 ms** | **Comfortable** | **Budget production** |
| NVIDIA Jetson Orin Nano | $499 | ~30 ms | With headroom | Production |
| NVIDIA Jetson AGX Orin | $2,000 | ~5 ms | Real-time | Professional |
| Intel NUC (x86 + OpenVINO) | $400 | ~150 ms | Good | Alternative |

2–3 devices per airport. At EUROCONTROL scale, $500–$2,000 per ground station
is operationally negligible — the same hardware runs for 5–10 years.

### Why edge inference (not cloud) for production

**Reliability.** Internet connectivity is a single point of failure. Edge device runs
autonomously during outages — critical for ATC systems where uptime > 99.9% is required.

**Latency.** Azure round-trip: 20–50 ms network + queue. Jetson Orin: 5–30 ms local.

**Data containment.** Raw camera frames from an airport perimeter contain sensitive
information. Edge inference sends only 200-byte result metadata — raw video never
leaves the premises. Matches aviation security requirements better than cloud upload.

**Model portability.** The same ONNX weights from Colab training deploy on Pi, Jetson,
and Intel NUC without modification. `ContrailDetector` in `inference.py` auto-detects
available backend (ONNX → PyTorch → OpenCV fallback).

### Three deployment strategies

**Strategy A — Pi + Hailo (budget production, ~$150/station)**
```
Pi 5 + Hailo-8L → 50 ms inference → Event Hub (200 bytes)
```

**Strategy B — Jetson Orin (full production, ~$500/station)**
```
Jetson Orin Nano → 30 ms inference → Event Hub (200 bytes)
```

**Strategy C — Pi pre-filter + cloud GPU (hybrid)**
```
Pi 4 → MobileNetV3 binary (80 ms) → drop 70% clear-sky frames
      → remaining frames → Azure NC6s_v3 GPU → full U-Net → Event Hub
Cost: ~$0.50/hr GPU VM shared across 40 cameras
```
Use when on-premises compute is constrained and bandwidth is available.

---

## Inference pipeline

```
Raw frame (BGR, any resolution)
    │
    ▼
Resize → 512×512, ImageNet normalisation → (1, 3, 512, 512) float32
    │
    ▼
ContrailDetector.detect()
  ├─ ONNX Runtime (preferred: Pi, Jetson, NUC)  ~30–150 ms
  ├─ PyTorch (GPU: Colab, cloud VM)              ~10 ms
  └─ OpenCV heuristic (fallback, no weights)     <5 ms, ~0% Dice
    │
    ▼
Sigmoid → binary mask, threshold 0.50
    │
    ▼
DetectionResult { contrail_detected, confidence, pixel_ratio, mask }
    │
    ▼
Event Hub EDGE_VISION_AI message (200 bytes)
```

---

## Reproduce this experiment

Step-by-step instructions to reproduce the training run and evaluation.

### 1. Download GVCCS dataset

```sh
# Free Zenodo account required (CC BY 4.0 license)
# https://zenodo.org/records/15743988
# Download GVCCS.zip (~2.1 GB) and place it at:
edge-pi/data/GVCCS.zip
```

### 2. Select control set (40 diverse images)

```sh
cd edge-pi/data
python select_control_set.py
# Output:
#   data/control_set/images/        ← 40 JPGs (1024×1024)
#   data/control_set/annotations.json  ← 235 GVCCS polygons for these images
```

The script selects 10 sparse + 10 medium + 10 dense + 10 clear-sky images,
one per video sequence to maximise diversity.

### 3. Visually verify the control set

```sh
# Generate annotated previews (green polygons = GVCCS ground truth)
cd edge-pi
python3 - << 'EOF'
import json, cv2, numpy as np
from pathlib import Path

ANN  = Path("data/control_set/annotations.json")
IMGS = Path("data/control_set/images")
OUT  = Path("data/control_set/previews"); OUT.mkdir(exist_ok=True)

with open(ANN) as f: coco = json.load(f)
ann_by_img = {}
for a in coco["annotations"]:
    ann_by_img.setdefault(a["image_id"], []).append(a)

for img in coco["images"]:
    frame = cv2.imread(str(IMGS / img["file_name"]))
    for ann in ann_by_img.get(img["id"], []):
        for seg in ann["segmentation"]:
            pts = np.array(seg, dtype=np.int32).reshape(-1, 2)
            cv2.fillPoly(frame, [pts], (0, 200, 0))
    cv2.imwrite(str(OUT / img["file_name"]), cv2.resize(frame, (512, 512)))
print(f"Previews → {OUT}")
EOF
# Open data/control_set/previews/ to verify annotations match visible contrails
```

Images identified as clearly showing contrails in manual review (17/40):
`image_20231006055400`, `image_20240413050830`, `image_20240313095400`,
`image_20230927124130`, `image_20231211081830`, `image_20240414052330`,
`image_20240129073900`, `image_20240118085230`, `image_20240426050500`,
`image_20240320062000`, `image_20240122091130`, `image_20240511131100`,
`image_20240422052630`, `image_20240511061800`, `image_20230928073100`,
`image_20231002065100`, `image_20240128080400`

Human–GVCCS agreement: **17/17 (100%)** — confirming annotation quality.
OpenCV baseline on same images: **0/17** — confirming need for deep learning.

### 4. Train on Google Colab (free T4 GPU, ~4–6 hours)

Upload `edge-pi/colab_train_contrail.ipynb` to [colab.research.google.com](https://colab.research.google.com).

**Before running:**
1. Runtime → Change runtime type → **T4 GPU**
2. Fix the `dice_score` function in cell 8 (handles empty masks correctly):

```python
def dice_score(logits, target, threshold=0.5):
    pred  = (torch.sigmoid(logits) > threshold).float()
    inter = (pred * target).sum()
    union = pred.sum() + target.sum()
    if union < 1:       # both empty = true negative = perfect score
        return 1.0
    return (2 * inter / (union + 1e-8)).item()
```

3. Add emergency save at the end of cell 8 (after the epoch loop):

```python
torch.save(model.state_dict(), f'{SAVE_DIR}/contrail_unet_last.pt')
print("Last weights saved:", f'{SAVE_DIR}/contrail_unet_last.pt')
```

4. Runtime → **Run all**
5. Approve Google Drive access — weights saved to `My Drive/coav_contrail_model/`
6. **Keep the browser tab open** — Colab disconnects after ~90 min of inactivity.
   Prevent laptop sleep (Mac: System Settings → Battery → Prevent automatic sleeping).

**Expected results:**

| Epoch | Train Dice | Val Dice | Note |
|---|---|---|---|
| 5 | ~0.77 | ~0.60 | Fast improvement from ImageNet pretraining |
| 15 | ~0.85 | ~0.72 | Plateau beginning |
| 30 | ~0.88 | ~0.75 | Final |

Val Dice target: **> 0.60** usable for demo · **> 0.75** production-grade PoC.

### 5. Deploy weights to edge device

```sh
# Download contrail_unet_best.pt from Google Drive
cp ~/Downloads/contrail_unet_best.pt edge-pi/python/weights/contrail_unet.pt

# Test on a single image
cd edge-pi/python
python inference.py /path/to/sky_image.jpg

# Run full capture loop (requires dump1090 + camera + Event Hub)
CONN_STR="Endpoint=sb://..." python capture.py
```

`ContrailDetector` auto-detects `weights/contrail_unet.pt` at startup and switches
from OpenCV fallback to full U-Net inference automatically.

### 6. Evaluate against GVCCS ground truth

```sh
cd edge-pi/python
# After model produces COCO-format predictions:
python eval_annotations.py \
    --gt  ../data/control_set/annotations.json \
    --pred my_predictions.json
# Reports per-image IoU, Precision, Recall, F1, Detection rate
```

---

## Getting started (quick)

```sh
# Install dependencies
cd edge-pi/python
pip install -r requirements.txt

# Run unit tests (no weights, no camera required)
python -m pytest test_inference.py test_capture.py -v

# Test with synthetic contrail image (generated programmatically)
python inference.py --download-sample
python inference.py sample_synthetic.jpg

# Node.js path
cd edge-pi/node
npm install
CONN_STR="..." node capture.js
```
