"""
Fine-tune ResUNet-34 on GVCCS ground-camera contrail data.

Dataset: GVCCS — Ground Visible Camera Contrail Sequences
  Source  : EUROCONTROL MUAC, Brétigny-sur-Orge, France
  Download: https://zenodo.org/records/15743988  (Zenodo DOI 10.5281/zenodo.15743988)
  Size    : 122 video sequences, 24,228 frames at 1024×1024, polygon annotations
  Format  : COCO-style JSON annotations, BGR frames as PNG

Pre-training:  ResNet-34 encoder from ImageNet (via segmentation_models_pytorch)
Fine-tuning:   GVCCS (~20 epochs, lr=1e-4)
Export:        weights/contrail_resunet34.pt  →  inference.py export_to_onnx()

Usage:
    python train.py --data /path/to/gvccs --epochs 20
    python inference.py --export-onnx        # after training: PT → ONNX for Pi
"""

import argparse
import json
import logging
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset, random_split

try:
    import segmentation_models_pytorch as smp
except ImportError as exc:
    raise SystemExit("Install: pip install segmentation-models-pytorch") from exc

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

INPUT_SIZE = (512, 512)
PIXEL_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
PIXEL_STD  = np.array([0.229, 0.224, 0.225], dtype=np.float32)


# ── Dataset ────────────────────────────────────────────────────────────────────

class GVCCSDataset(Dataset):
    """
    Loads GVCCS frames and converts polygon annotations to binary masks.

    Expected layout (after extracting Zenodo archive):
      <root>/images/   — PNG frames (sequence_NNNN_frame_MMMM.png)
      <root>/annotations.json  — COCO-format annotations
    """

    def __init__(self, root: Path, augment: bool = False):
        self.root    = root
        self.augment = augment
        ann_path     = root / "annotations.json"
        with open(ann_path) as f:
            coco = json.load(f)

        self.images      = {img["id"]: img for img in coco["images"]}
        self.annotations = {}
        for ann in coco["annotations"]:
            self.annotations.setdefault(ann["image_id"], []).append(ann)
        self.ids = list(self.images.keys())

    def __len__(self) -> int:
        return len(self.ids)

    def __getitem__(self, idx: int):
        img_id  = self.ids[idx]
        img_meta = self.images[img_id]
        frame   = cv2.imread(str(self.root / "images" / img_meta["file_name"]))
        h, w    = frame.shape[:2]

        # Build binary mask from polygon annotations
        mask = np.zeros((h, w), dtype=np.uint8)
        for ann in self.annotations.get(img_id, []):
            for seg in ann.get("segmentation", []):
                pts = np.array(seg, dtype=np.int32).reshape(-1, 2)
                cv2.fillPoly(mask, [pts], 1)

        # Resize + normalise
        frame_r = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
                             INPUT_SIZE).astype(np.float32) / 255.0
        frame_r = (frame_r - PIXEL_MEAN) / PIXEL_STD
        mask_r  = cv2.resize(mask, INPUT_SIZE, interpolation=cv2.INTER_NEAREST)

        if self.augment:
            frame_r, mask_r = _augment(frame_r, mask_r)

        return (
            torch.from_numpy(frame_r.transpose(2, 0, 1)),   # (3, H, W)
            torch.from_numpy(mask_r).unsqueeze(0).float(),  # (1, H, W)
        )


def _augment(frame: np.ndarray, mask: np.ndarray):
    """Horizontal flip (p=0.5) — sufficient for linear contrail structures."""
    if np.random.rand() < 0.5:
        frame = np.fliplr(frame).copy()
        mask  = np.fliplr(mask).copy()
    return frame, mask


# ── Training ───────────────────────────────────────────────────────────────────

def train(data_root: Path, epochs: int, batch_size: int, lr: float,
          out_path: Path, val_split: float = 0.15) -> None:

    dataset = GVCCSDataset(data_root, augment=True)
    n_val   = max(1, int(len(dataset) * val_split))
    n_train = len(dataset) - n_val
    train_ds, val_ds = random_split(dataset, [n_train, n_val])
    logger.info("Dataset: %d train / %d val frames", n_train, n_val)

    train_dl = DataLoader(train_ds, batch_size=batch_size, shuffle=True,
                          num_workers=2, pin_memory=True)
    val_dl   = DataLoader(val_ds,   batch_size=batch_size, shuffle=False,
                          num_workers=2)

    model = smp.Unet(
        encoder_name="resnet34",
        encoder_weights="imagenet",   # transfer learning from ImageNet
        in_channels=3,
        classes=1,
        activation=None,
    )
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("Training on %s", device)
    model = model.to(device)

    # Dice + BCE combined loss (standard for medical / remote sensing segmentation)
    criterion = smp.losses.DiceLoss(mode="binary") + smp.losses.SoftBCEWithLogitsLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    best_val_loss = float("inf")

    for epoch in range(1, epochs + 1):
        # ── Train
        model.train()
        train_loss = 0.0
        for frames, masks in train_dl:
            frames, masks = frames.to(device), masks.to(device)
            optimizer.zero_grad()
            loss = criterion(model(frames), masks)
            loss.backward()
            optimizer.step()
            train_loss += loss.item()
        train_loss /= len(train_dl)

        # ── Validate
        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for frames, masks in val_dl:
                frames, masks = frames.to(device), masks.to(device)
                val_loss += criterion(model(frames), masks).item()
        val_loss /= len(val_dl)
        scheduler.step()

        logger.info("Epoch %02d/%02d  train=%.4f  val=%.4f", epoch, epochs,
                    train_loss, val_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            torch.save(model.cpu().state_dict(), out_path)
            model = model.to(device)
            logger.info("  ↳ saved best model → %s", out_path)

    logger.info("Training complete. Best val loss: %.4f", best_val_loss)
    logger.info("Next: python inference.py --export-onnx   (for Raspberry Pi deployment)")


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Fine-tune ResUNet-34 on GVCCS dataset")
    ap.add_argument("--data",       required=True, type=Path,
                    help="Path to GVCCS root (contains images/ and annotations.json)")
    ap.add_argument("--epochs",     type=int,   default=20)
    ap.add_argument("--batch-size", type=int,   default=8)
    ap.add_argument("--lr",         type=float, default=1e-4)
    ap.add_argument("--out",        type=Path,
                    default=Path(__file__).parent / "weights" / "contrail_resunet34.pt")
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    train(args.data, args.epochs, args.batch_size, args.lr, args.out)
