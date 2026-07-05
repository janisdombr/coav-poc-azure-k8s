#!/usr/bin/env python3
"""
Offline precompute of real U-Net inference results for the emulator camera
channel — "variant B" (precompute offline → replay in the cloud).

Why: the cloud emulator image ships only numpy+opencv (no torch, no
segmentation_models_pytorch — see requirements.txt). Running the real trained
U-Net there is impossible. Instead we run the model ONCE, locally, over the 96
held-out GVCCS val frames (edge-emulator/frames/, manifest.json) and bake the
results into edge-emulator/frames/precomputed.json. At runtime CameraProducer
replays that bundle (base64 decode + opencv only) so the cloud demo shows real
model output, not an OpenCV heuristic, without ever importing torch.

Usage (local machine, with edge-pi weights + segmentation_models_pytorch installed):
    cd edge-emulator
    python3 precompute_inference.py

Requires:
    - edge-pi/python/inference.py + weights (edge-pi/data/contrail_unet_best.pt
      or edge-pi/python/weights/contrail_unet.pt)
    - segmentation_models_pytorch + torch installed LOCALLY ONLY — never added
      to edge-emulator/requirements.txt / the cloud image.

Fails loudly (non-zero exit) if the real pytorch backend does not load — a
precompute run on the OpenCV fallback would defeat the entire purpose.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from emulator import (  # noqa: E402  (path insert must happen first)
    CameraProducer, FRAMES_DIR, INFERENCE_DIR, MASK_MAX_SIDE, MIN_COMPONENT_PX,
)

sys.path.insert(0, INFERENCE_DIR)
from inference import ContrailDetector, DEFAULT_THRESHOLD  # noqa: E402

OUT_PATH = FRAMES_DIR / "precomputed.json"


def _count_components(binary: np.ndarray) -> int:
    """Same connected-components rule as CameraProducer._temporal_delta,
    without the per-camera temporal state (that only exists at replay time)."""
    n_labels, _labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    return sum(1 for lab in range(1, n_labels)
               if stats[lab, cv2.CC_STAT_AREA] >= MIN_COMPONENT_PX)


def main() -> None:
    manifest_path = FRAMES_DIR / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"{manifest_path} not found — run prepare_val_frames.py first")
    with open(manifest_path) as f:
        manifest = json.load(f)
    frame_entries = manifest["frames"]

    detector = ContrailDetector(threshold=DEFAULT_THRESHOLD, use_tta=False)
    if detector._backend != "pytorch":
        raise SystemExit(
            f"ContrailDetector backend='{detector._backend}', expected 'pytorch'. "
            "No real weights loaded (or segmentation_models_pytorch missing) — "
            "precompute would just bake in the OpenCV heuristic, which is pointless. "
            "pip install segmentation-models-pytorch locally and ensure "
            "edge-pi/data/contrail_unet_best.pt (or edge-pi/python/weights/contrail_unet.pt) exists."
        )
    print(f"[precompute] backend={detector._backend}  threshold={detector.threshold}  "
          f"tta={detector.use_tta}")

    bundle_frames: dict[str, dict] = {}
    n_detected = 0
    for i, entry in enumerate(frame_entries):
        ref  = entry["frame_ref"]
        path = HERE / "frames" / entry["file"]
        frame = cv2.imread(str(path))
        if frame is None:
            print(f"  WARNING: unreadable frame {path} — skipped")
            continue

        result = detector.detect(frame)  # full-resolution DetectionResult
        small  = CameraProducer._downscale_mask((result.mask > 0).astype(np.uint8) * 255)
        binary = (small > 0).astype(np.uint8)
        contrail_count = _count_components(binary)
        detected = bool(result.contrail_detected and contrail_count > 0)
        if detected:
            n_detected += 1

        # Visualisation: downscaled frame with detected contrails painted red —
        # identical rendering to the live path (CameraProducer._analyse).
        viz_frame = cv2.resize(frame, (small.shape[1], small.shape[0]))
        if detected:
            viz_frame = viz_frame.copy()
            viz_frame[binary > 0] = [0, 0, 255]
        ok_jpeg, jpeg_buf = cv2.imencode(".jpg", viz_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
        if not ok_jpeg:
            print(f"  WARNING: JPEG encode failed for {ref} — skipped")
            continue

        # Binary mask (0/255) at the same downscale — PNG is lossless and tiny for
        # a mostly-black binary image; needed at replay time to redo the connected-
        # components / temporal-delta logic per camera (see _temporal_delta).
        ok_png, png_buf = cv2.imencode(".png", (binary * 255).astype(np.uint8))
        if not ok_png:
            print(f"  WARNING: PNG mask encode failed for {ref} — skipped")
            continue

        bundle_frames[ref] = {
            "confidence":      round(float(result.confidence), 3),
            "pixel_ratio":     round(float(result.pixel_ratio), 6),
            "contrail_count":  contrail_count,
            "mask_small_b64":  base64.b64encode(png_buf).decode("ascii"),
            "viz_jpeg_b64":    base64.b64encode(jpeg_buf).decode("ascii"),
        }
        print(f"  [{i+1:3d}/{len(frame_entries)}] {ref:18s} "
              f"detected={detected!s:5s} conf={result.confidence:.3f} "
              f"pixel_ratio={result.pixel_ratio:.4%} contrails={contrail_count}")

    bundle = {
        "backend":    detector._backend,
        "threshold":  detector.threshold,
        "use_tta":    detector.use_tta,
        "n_frames":   len(bundle_frames),
        "n_detected": n_detected,
        "frames":     bundle_frames,
    }
    with open(OUT_PATH, "w") as f:
        json.dump(bundle, f)

    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"\n[precompute] backend={detector._backend}  "
          f"frames={len(bundle_frames)}/{len(frame_entries)}  "
          f"detected={n_detected}  bundle={OUT_PATH}  size={size_kb:.1f} KB")


if __name__ == "__main__":
    main()
