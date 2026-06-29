"""
Compare two COCO annotation files (ground-truth vs predicted / manually annotated).

Used to:
  1. Measure agreement between manual labels and GVCCS ground-truth
  2. Evaluate model predictions against ground-truth after training

Metrics reported:
  - IoU (Intersection over Union) per image, averaged over the set
  - Precision / Recall / F1  at pixel level
  - Detection rate (≥1 contrail predicted when ≥1 contrail present)

Usage:
  # Compare GVCCS annotations vs your manual labels (after LabelMe → COCO conversion):
  python eval_annotations.py \\
      --gt  ../data/control_set/annotations.json \\
      --pred my_labels.json

  # Evaluate model mask outputs (saved as PNG binary masks):
  python eval_annotations.py \\
      --gt  ../data/control_set/annotations.json \\
      --mask-dir model_outputs/
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def coco_to_masks(ann_path: Path, image_dir: Path | None = None,
                  image_size: tuple[int, int] = (1024, 1024)) -> dict[str, np.ndarray]:
    """Convert COCO polygon annotations → dict of binary masks keyed by filename."""
    with open(ann_path) as f:
        coco = json.load(f)

    img_meta = {img["id"]: img for img in coco["images"]}
    ann_by_img = {}
    for ann in coco["annotations"]:
        ann_by_img.setdefault(ann["image_id"], []).append(ann)

    masks = {}
    for img in coco["images"]:
        h = img.get("height", image_size[0])
        w = img.get("width",  image_size[1])
        mask = np.zeros((h, w), dtype=np.uint8)
        for ann in ann_by_img.get(img["id"], []):
            for seg in ann.get("segmentation", []):
                pts = np.array(seg, dtype=np.int32).reshape(-1, 2)
                cv2.fillPoly(mask, [pts], 1)
        masks[img["file_name"]] = mask
    return masks


def mask_iou(m1: np.ndarray, m2: np.ndarray) -> float:
    inter = np.logical_and(m1, m2).sum()
    union = np.logical_or(m1,  m2).sum()
    return float(inter / union) if union > 0 else 1.0  # both empty → perfect match


def pixel_metrics(gt: np.ndarray, pred: np.ndarray) -> dict:
    # Both empty = true negative = perfect score
    if not gt.any() and not pred.any():
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    tp = np.logical_and(gt,                  pred).sum()
    fp = np.logical_and(np.logical_not(gt),  pred).sum()
    fn = np.logical_and(gt,  np.logical_not(pred)).sum()
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def evaluate(gt_path: Path, pred_path: Path | None = None,
             mask_dir: Path | None = None) -> None:
    print(f"Ground-truth: {gt_path}")

    gt_masks = coco_to_masks(gt_path)

    if pred_path:
        print(f"Predictions:  {pred_path}")
        pred_masks = coco_to_masks(pred_path)
    elif mask_dir:
        print(f"Mask dir:     {mask_dir}")
        pred_masks = {}
        for fname in gt_masks:
            stem = Path(fname).stem
            for ext in (".png", ".jpg", ".jpeg"):
                mp = mask_dir / (stem + ext)
                if mp.exists():
                    m = cv2.imread(str(mp), cv2.IMREAD_GRAYSCALE)
                    pred_masks[fname] = (m > 127).astype(np.uint8)
                    break
    else:
        raise ValueError("Provide --pred or --mask-dir")

    common = sorted(set(gt_masks) & set(pred_masks))
    print(f"\nImages in common: {len(common)} / {len(gt_masks)} GT images\n")

    ious, precs, recs, f1s = [], [], [], []
    print(f"{'Image':<45} {'IoU':>6} {'Prec':>6} {'Rec':>6} {'F1':>6}  {'GT':>4} {'Pred':>4}")
    print("-" * 82)

    for fname in common:
        gt   = gt_masks[fname]
        pred = pred_masks.get(fname, np.zeros_like(gt))
        iou  = mask_iou(gt, pred)
        m    = pixel_metrics(gt, pred)
        ious.append(iou)
        precs.append(m["precision"])
        recs.append(m["recall"])
        f1s.append(m["f1"])
        gt_pos   = "yes" if gt.any()   else " no"
        pred_pos = "yes" if pred.any() else " no"
        print(f"{fname:<45} {iou:6.3f} {m['precision']:6.3f} {m['recall']:6.3f} {m['f1']:6.3f}"
              f"  {gt_pos:>4} {pred_pos:>4}")

    print("-" * 82)
    print(f"{'MEAN':<45} {np.mean(ious):6.3f} {np.mean(precs):6.3f} "
          f"{np.mean(recs):6.3f} {np.mean(f1s):6.3f}")
    print(f"\n  Mean IoU:       {np.mean(ious):.3f}")
    print(f"  Mean Precision: {np.mean(precs):.3f}")
    print(f"  Mean Recall:    {np.mean(recs):.3f}")
    print(f"  Mean F1:        {np.mean(f1s):.3f}")

    # Detection rate: did we find at least one contrail when one was present?
    gt_pos   = sum(1 for f in common if gt_masks[f].any())
    pred_pos_when_gt = sum(
        1 for f in common if gt_masks[f].any() and pred_masks.get(f, np.zeros(1)).any()
    )
    print(f"\n  Detection rate: {pred_pos_when_gt}/{gt_pos} images "
          f"({100*pred_pos_when_gt/gt_pos:.0f}%)" if gt_pos > 0 else "")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Evaluate contrail segmentation vs COCO ground-truth")
    ap.add_argument("--gt",       required=True, type=Path, help="Ground-truth COCO JSON")
    ap.add_argument("--pred",     type=Path, help="Predicted COCO JSON (e.g. LabelMe output)")
    ap.add_argument("--mask-dir", type=Path, help="Directory of binary PNG masks (one per image)")
    args = ap.parse_args()
    evaluate(args.gt, args.pred, args.mask_dir)
