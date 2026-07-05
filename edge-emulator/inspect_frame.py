#!/usr/bin/env python3
"""
Manual single-frame inspection tool for the COAV contrail detector (Day 11 / P1 debug aid).

Runs the real ContrailDetector (edge-pi/python/inference.py) on ONE frame at
FULL resolution. The live emulator pipeline downsamples masks to a
MASK_MAX_SIDE=256 thumbnail for the EDGE_VISION_AI payload — this tool exists
so a human can look at the actual model output at full size and judge
"the model is wrong" vs. "it's just hard to see on the mini thumbnail".

Usage:
    python3 inspect_frame.py gvccs_val_00038
    python3 inspect_frame.py frames/image_20230927124130.jpg
    python3 inspect_frame.py image_20230927124130.jpg --threshold 0.6
    python3 inspect_frame.py gvccs_val_00038 --sweep

Output:
    stdout : file, backend, confidence, contrail_pixel_ratio, contrail_count
    PNG    : /tmp/inspect_<frame_ref_or_stem>.png — full-res side-by-side
             (input | red mask overlay)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

HERE          = Path(__file__).resolve().parent
FRAMES_DIR    = HERE / "frames"
MANIFEST_PATH = FRAMES_DIR / "manifest.json"
INFERENCE_DIR = HERE.parent / "edge-pi" / "python"

if str(INFERENCE_DIR) not in sys.path:
    sys.path.insert(0, str(INFERENCE_DIR))

from inference import ContrailDetector, DEFAULT_THRESHOLD  # noqa: E402

# Mirror of edge-emulator/emulator.py's connected-component filtering
# (MASK_MAX_SIDE / MIN_COMPONENT_PX), so contrail_count here is comparable to
# what the live EDGE_VISION_AI payload reports, just computed at full res.
MASK_MAX_SIDE    = 256
MIN_COMPONENT_PX = 12

SWEEP_THRESHOLDS = (0.35, 0.45, 0.50, 0.60)


def resolve_frame(ref_or_path: str) -> Path:
    """
    Resolve a CLI argument to an image file:
      1. Direct path that exists as-is (relative or absolute).
      2. A bare filename under edge-emulator/frames/.
      3. A frame_ref (e.g. "gvccs_val_00038") looked up in frames/manifest.json.
    """
    direct = Path(ref_or_path)
    if direct.exists():
        return direct

    under_frames = FRAMES_DIR / ref_or_path
    if under_frames.exists():
        return under_frames

    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH) as f:
            manifest = json.load(f)
        for entry in manifest.get("frames", []):
            if entry["frame_ref"] == ref_or_path:
                path = FRAMES_DIR / entry["file"]
                if path.exists():
                    return path
                raise FileNotFoundError(f"manifest points to missing file: {path}")

    raise FileNotFoundError(
        f"Could not resolve '{ref_or_path}' as a file path, a filename under "
        f"{FRAMES_DIR}, or a frame_ref in {MANIFEST_PATH}"
    )


def count_components(mask: np.ndarray) -> int:
    """
    Connected components on the full-resolution binary mask. The min-area
    filter is scaled up from MIN_COMPONENT_PX (defined at the 256px mask
    payload scale in emulator.py) to full resolution, so counts are
    comparable to what the live pipeline reports.
    """
    h, w = mask.shape[:2]
    scale = MASK_MAX_SIDE / max(h, w)
    min_area = MIN_COMPONENT_PX if scale >= 1.0 else MIN_COMPONENT_PX / (scale ** 2)
    binary = (mask > 0).astype(np.uint8)
    n_labels, _labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    return sum(1 for lab in range(1, n_labels) if stats[lab, cv2.CC_STAT_AREA] >= min_area)


def make_side_by_side(frame_bgr: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Input frame | red mask overlay, both at full input resolution."""
    overlay = frame_bgr.copy()
    overlay[mask > 0] = [0, 0, 255]   # solid red — same visualisation as emulator.py
    separator = np.full((frame_bgr.shape[0], 4, 3), (255, 255, 0), dtype=np.uint8)
    return np.hstack([frame_bgr, separator, overlay])


def run_at_threshold(detector: ContrailDetector, frame: np.ndarray, threshold: float):
    detector.threshold = threshold
    result = detector.detect(frame)
    count = count_components(result.mask)
    return result, count


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Run the real ContrailDetector on one frame at full resolution.")
    ap.add_argument("frame", help="frame_ref (gvccs_val_NNNNN), filename under frames/, or a direct path")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                    help=f"sigmoid threshold (default: {DEFAULT_THRESHOLD})")
    ap.add_argument("--sweep", action="store_true",
                    help=f"also report count/pixel_ratio at thresholds {SWEEP_THRESHOLDS}")
    args = ap.parse_args()

    path = resolve_frame(args.frame)
    frame = cv2.imread(str(path))
    if frame is None:
        print(f"Cannot read image: {path}")
        sys.exit(1)

    detector = ContrailDetector(threshold=args.threshold)
    result, count = run_at_threshold(detector, frame, args.threshold)

    print(f"File              : {path}")
    print(f"Resolution        : {frame.shape[1]}x{frame.shape[0]}")
    print(f"Backend           : {result.backend}")
    print(f"Confidence        : {result.confidence:.3f}")
    print(f"Contrail_pixel_ratio : {result.pixel_ratio:.4%}")
    print(f"Contrail_count    : {count}")
    print(f"Threshold         : {args.threshold:.2f}")

    if args.sweep:
        print("\nThreshold sweep:")
        print(f"{'t':>6} {'count':>6} {'pixel_ratio':>12}")
        for t in SWEEP_THRESHOLDS:
            r, c = run_at_threshold(detector, frame, t)
            print(f"{t:6.2f} {c:6d} {r.pixel_ratio:12.4%}")
        # restore requested threshold for the saved overlay
        result, count = run_at_threshold(detector, frame, args.threshold)

    label = args.frame
    if "/" in label or label.lower().endswith((".jpg", ".jpeg", ".png")):
        label = Path(label).stem
    out_path = Path(f"/tmp/inspect_{label}.png")
    cv2.imwrite(str(out_path), make_side_by_side(frame, result.mask))
    print(f"\nSaved side-by-side PNG -> {out_path}")


if __name__ == "__main__":
    main()
