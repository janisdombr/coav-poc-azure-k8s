#!/usr/bin/env python3
"""
Extract held-out GVCCS *val* frames for the emulator camera channel (Day 11 / P1).

Reproduces EXACTLY the train/val split from edge-pi/python/train.py:

    random.seed(42)
    all_idx = list(range(n_total))
    random.shuffle(all_idx)
    val_idx = all_idx[:int(n_total * 0.1)]

so the emulator only streams frames the U-Net never saw during training.
(The old edge-pi/data/control_set was sampled from the TRAIN portion —
using it for live verification would be data leakage; this replaces it.)

Output:
    edge-emulator/frames/<image>.jpg     — extracted val frames
    edge-emulator/frames/manifest.json   — frame_ref ↔ file mapping + split metadata

frame_ref = "gvccs_val_NNNNN" where NNNNN is the position inside the val split
(stable across runs — same seed, same ordering as train.py).

Usage:
    cd edge-emulator
    python prepare_val_frames.py                # 96 frames → ./frames/
    python prepare_val_frames.py --limit 200
"""

import argparse
import json
import random
import shutil
import zipfile
from pathlib import Path

HERE      = Path(__file__).resolve().parent
DEF_ZIP   = HERE.parent / "edge-pi" / "data" / "GVCCS.zip"
DEF_ANN   = HERE.parent / "edge-pi" / "data" / "GVCCS" / "train" / "annotations.json"
DEF_OUT   = HERE / "frames"

SEED         = 42     # must match train.py
VAL_FRACTION = 0.1    # must match train.py


def val_indices(n_total: int) -> list[int]:
    """Exact copy of the split logic in train.py (same seed, same order)."""
    rng = random.Random(SEED)          # identical stream to random.seed(42)
    all_idx = list(range(n_total))
    rng.shuffle(all_idx)
    return all_idx[:int(n_total * VAL_FRACTION)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--zip", default=str(DEF_ZIP),
                    help="GVCCS.zip (Zenodo 15743988)")
    ap.add_argument("--annotations", default=str(DEF_ANN),
                    help="GVCCS train annotations.json (defines image ordering)")
    ap.add_argument("--out", default=str(DEF_OUT), help="Output frames directory")
    ap.add_argument("--limit", type=int, default=96,
                    help="Number of val frames to extract (default: 96)")
    args = ap.parse_args()

    ann_path = Path(args.annotations)
    out_dir  = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading {ann_path} …")
    with open(ann_path) as f:
        images = json.load(f)["images"]
    n_total = len(images)

    val_idx = val_indices(n_total)
    print(f"Split reproduced: total={n_total}  val={len(val_idx)}  "
          f"(seed={SEED}, fraction={VAL_FRACTION} — same as train.py)")

    # First N val frames (val-split order), then sort chronologically so the
    # emulator's temporal delta (new_contrail_count) is meaningful.
    selected = [(pos, images[ds_idx], ds_idx)
                for pos, ds_idx in enumerate(val_idx[:args.limit])]
    selected.sort(key=lambda s: s[1].get("time", ""))

    # ── Copy frames: prefer extracted images dir, else pull from GVCCS.zip ────
    img_dir  = ann_path.parent / "images"
    zip_path = Path(args.zip)
    zf = None
    if not img_dir.is_dir():
        if not zip_path.exists():
            raise SystemExit(f"Neither {img_dir} nor {zip_path} found — "
                             "download GVCCS from Zenodo 15743988 first.")
        zf = zipfile.ZipFile(zip_path)
        members = set(zf.namelist())

    manifest_frames = []
    extracted = 0
    for pos, meta, ds_idx in selected:
        fname = meta["file_name"]
        dest  = out_dir / fname
        if not dest.exists():
            if zf is None:
                src = img_dir / fname
                if not src.exists():
                    print(f"  WARNING: {src} missing — skipped")
                    continue
                shutil.copyfile(src, dest)
            else:
                zpath = f"GVCCS/train/images/{fname}"
                if zpath not in members:
                    print(f"  WARNING: {zpath} not in zip — skipped")
                    continue
                with zf.open(zpath) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        extracted += 1
        manifest_frames.append({
            "frame_ref":     f"gvccs_val_{pos:05d}",
            "file":          fname,
            "image_id":      meta["id"],
            "dataset_index": ds_idx,
            "time":          meta.get("time"),
        })
    if zf is not None:
        zf.close()

    manifest = {
        "dataset":      "GVCCS (Zenodo 15743988, CC BY 4.0, EUROCONTROL MUAC)",
        "split":        "val (held-out — model never trained on these frames)",
        "seed":         SEED,
        "val_fraction": VAL_FRACTION,
        "n_total":      n_total,
        "n_val":        len(val_idx),
        "frames":       manifest_frames,
    }
    with open(out_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"Done: {extracted} val frames → {out_dir}")
    print(f"Manifest → {out_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
