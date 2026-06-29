"""
Contrail detection via semantic segmentation.

Architecture : ResUNet-34  (ResNet-34 encoder + U-Net decoder with skip connections)
Training data: GVCCS — 24,228 frames from EUROCONTROL MUAC ground cameras, Brétigny-sur-Orge
               (Zenodo: 10.5281/zenodo.15743988)
               + Google OpenContrails GOES-16 satellite imagery for pre-training
Inference    : ONNX Runtime (CPU-optimised, recommended for Raspberry Pi ARM)
               Falls back to PyTorch → OpenCV heuristic if ONNX Runtime unavailable

Usage:
    detector = ContrailDetector()               # loads model once
    result   = detector.detect(frame_bgr)       # frame = numpy array from OpenCV/picamera2
    print(result.contrail_detected, result.confidence)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ── Model config ───────────────────────────────────────────────────────────────
MODEL_DIR   = Path(__file__).parent / "weights"
ONNX_PATH   = MODEL_DIR / "contrail_resunet34.onnx"
PT_PATH     = MODEL_DIR / "contrail_resunet34.pt"

INPUT_SIZE  = (512, 512)          # model input resolution
PIXEL_MEAN  = [0.485, 0.456, 0.406]   # ImageNet normalisation (also used by GVCCS fine-tune)
PIXEL_STD   = [0.229, 0.224, 0.225]

# Contrail present if ≥ this fraction of pixels are positive (avoids false positives on thin lines)
PIXEL_RATIO_THRESHOLD = 0.001     # 0.1% of frame — roughly 250 pixels at 512×512
CONFIDENCE_THRESHOLD  = 0.45     # sigmoid output threshold for binary mask


@dataclass
class DetectionResult:
    contrail_detected: bool
    confidence: float                     # mean sigmoid probability in detected region (0–1)
    pixel_ratio: float                    # fraction of frame covered by contrail mask
    mask: np.ndarray = field(repr=False)  # binary mask, same resolution as input frame
    backend: str = "unknown"             # "onnx" | "pytorch" | "opencv"


class ContrailDetector:
    """
    Loads once, detects on every frame.  Thread-safe (ONNX session is stateless).

    Priority:
      1. ONNX Runtime  — fastest on ARM, ~60 ms/frame on Pi 4
      2. PyTorch       — if onnxruntime not installed
      3. OpenCV        — pure-heuristic fallback (no learned weights)
    """

    def __init__(self, confidence_threshold: float = CONFIDENCE_THRESHOLD):
        self.confidence_threshold = confidence_threshold
        self._session = None    # ONNX InferenceSession
        self._model   = None    # PyTorch nn.Module
        self._backend = "opencv"
        self._init_model()

    # ── Initialisation ─────────────────────────────────────────────────────────

    def _init_model(self) -> None:
        if ONNX_PATH.exists():
            self._load_onnx()
        elif PT_PATH.exists():
            self._load_pytorch()
        else:
            logger.warning(
                "No model weights found in %s — using OpenCV heuristic fallback. "
                "Run download_weights() to fetch pre-trained weights.", MODEL_DIR
            )

    def _load_onnx(self) -> None:
        try:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 2   # conservative: leave cores for camera I/O
            self._session = ort.InferenceSession(
                str(ONNX_PATH),
                sess_options=opts,
                providers=["CPUExecutionProvider"]
            )
            self._backend = "onnx"
            logger.info("ContrailDetector: ONNX backend loaded (%s)", ONNX_PATH.name)
        except ImportError:
            logger.warning("onnxruntime not installed — trying PyTorch backend")
            self._load_pytorch()

    def _load_pytorch(self) -> None:
        try:
            import torch
            self._model = _build_resunet34()
            state = torch.load(str(PT_PATH), map_location="cpu")
            self._model.load_state_dict(state)
            self._model.eval()
            self._backend = "pytorch"
            logger.info("ContrailDetector: PyTorch backend loaded (%s)", PT_PATH.name)
        except ImportError:
            logger.warning("torch not installed — using OpenCV heuristic fallback")

    # ── Public API ─────────────────────────────────────────────────────────────

    def detect(self, frame_bgr: np.ndarray) -> DetectionResult:
        """
        Run contrail segmentation on a single BGR frame (from OpenCV or picamera2).

        Args:
            frame_bgr: numpy array, shape (H, W, 3), dtype uint8

        Returns:
            DetectionResult with mask at original frame resolution
        """
        if self._backend == "onnx":
            return self._detect_onnx(frame_bgr)
        if self._backend == "pytorch":
            return self._detect_pytorch(frame_bgr)
        return self._detect_opencv(frame_bgr)

    # ── ONNX inference ─────────────────────────────────────────────────────────

    def _detect_onnx(self, frame_bgr: np.ndarray) -> DetectionResult:
        tensor = _preprocess(frame_bgr)                  # (1, 3, H, W) float32
        inputs = {self._session.get_inputs()[0].name: tensor}
        logits = self._session.run(None, inputs)[0]      # (1, 1, H, W)
        prob   = 1.0 / (1.0 + np.exp(-logits[0, 0]))    # sigmoid
        return self._postprocess(prob, frame_bgr.shape[:2], "onnx")

    # ── PyTorch inference ──────────────────────────────────────────────────────

    def _detect_pytorch(self, frame_bgr: np.ndarray) -> DetectionResult:
        import torch
        tensor = torch.from_numpy(_preprocess(frame_bgr))
        with torch.no_grad():
            logits = self._model(tensor)[0, 0]           # (H, W)
        prob = torch.sigmoid(logits).numpy()
        return self._postprocess(prob, frame_bgr.shape[:2], "pytorch")

    # ── OpenCV heuristic fallback ──────────────────────────────────────────────
    # Detects bright, elongated linear structures on a sky background.
    # Precision is low — suitable only when no model weights are available.

    def _detect_opencv(self, frame_bgr: np.ndarray) -> DetectionResult:
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)

        # Sky is usually bright in the upper part of the frame
        sky_region = gray[:gray.shape[0] // 2, :]
        _, bright  = cv2.threshold(sky_region, 200, 255, cv2.THRESH_BINARY)

        # Contrails = elongated bright lines → detect with HoughLinesP
        edges = cv2.Canny(bright, 50, 150)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=80,
                                minLineLength=80, maxLineGap=20)

        # mask covers only the sky_region (top half) — line coords from HoughLines
        # are in sky_region coordinate space (y: 0 .. H//2)
        mask = np.zeros(sky_region.shape[:2], dtype=np.float32)
        if lines is not None:
            for x1, y1, x2, y2 in lines[:, 0]:
                cv2.line(mask, (x1, y1), (x2, y2), 1.0, 8)

        pixel_ratio = float(mask.sum()) / mask.size
        confidence  = min(pixel_ratio * 20, 0.85)   # crude scaling — NOT reliable
        detected    = pixel_ratio > PIXEL_RATIO_THRESHOLD

        full_mask = np.zeros(frame_bgr.shape[:2], dtype=np.uint8)
        full_mask[:sky_region.shape[0]] = (mask * 255).astype(np.uint8)
        return DetectionResult(detected, confidence, pixel_ratio, full_mask, "opencv")

    # ── Shared post-processing ─────────────────────────────────────────────────

    def _postprocess(
        self, prob: np.ndarray, orig_hw: tuple[int, int], backend: str
    ) -> DetectionResult:
        # Upsample mask back to original frame resolution
        mask_512 = (prob > self.confidence_threshold).astype(np.uint8) * 255
        mask_orig = cv2.resize(mask_512, (orig_hw[1], orig_hw[0]),
                               interpolation=cv2.INTER_NEAREST)

        pixel_ratio = float((mask_orig > 0).sum()) / mask_orig.size

        # Confidence = mean sigmoid probability inside detected pixels (or global mean)
        if pixel_ratio > 0:
            confidence = float(prob[prob > self.confidence_threshold].mean())
        else:
            confidence = float(prob.mean())

        detected = pixel_ratio > PIXEL_RATIO_THRESHOLD
        return DetectionResult(detected, round(confidence, 3), round(pixel_ratio, 6),
                               mask_orig, backend)


# ── Model architecture (ResUNet-34) ───────────────────────────────────────────

def _build_resunet34():
    """
    ResUNet-34: ResNet-34 encoder with U-Net skip connections + sigmoid output.
    Matches the architecture in junzis/contrail-seg and GVCCS fine-tuning experiments.

    Install:  pip install segmentation-models-pytorch
    """
    try:
        import segmentation_models_pytorch as smp
        return smp.Unet(
            encoder_name="resnet34",
            encoder_weights=None,    # weights loaded separately from PT_PATH
            in_channels=3,
            classes=1,
            activation=None,         # raw logits; sigmoid applied in postprocess
        )
    except ImportError as exc:
        raise RuntimeError(
            "segmentation-models-pytorch required for PyTorch backend. "
            "Install with: pip install segmentation-models-pytorch"
        ) from exc


# ── Pre-processing ─────────────────────────────────────────────────────────────

def _preprocess(frame_bgr: np.ndarray) -> np.ndarray:
    """BGR frame → normalised (1, 3, 512, 512) float32 tensor (NumPy)."""
    rgb   = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    sized = cv2.resize(rgb, INPUT_SIZE)
    normed = (sized.astype(np.float32) / 255.0 - PIXEL_MEAN) / PIXEL_STD
    return normed.transpose(2, 0, 1)[np.newaxis].astype(np.float32)  # NCHW


# ── Weight download helper ─────────────────────────────────────────────────────

def download_weights(target_dir: Path = MODEL_DIR) -> Path:
    """
    Downloads pre-trained contrail-seg weights (PyTorch, satellite-domain).

    Source: junzis/contrail-seg — ResUNet-34 trained on GOES-16 satellite imagery
    (Google Contrails Kaggle dataset).  Weights are hosted on SurfDrive, NOT GitHub
    releases (the repo has no releases).

    NOTE: These weights were trained on satellite imagery (top-down, high altitude).
    For ground-camera deployment (Raspberry Pi), fine-tune on GVCCS afterwards:
      python train.py --data /path/to/GVCCS --epochs 20
      python inference.py --export-onnx

    Download steps (manual — SurfDrive requires browser login):
      1. Open https://surfdrive.surf.nl/files/index.php/s/n1b0L2qfu2PZ6d3
      2. Download the .pt file
      3. Copy to: edge-pi/python/weights/contrail_resunet34.pt

    Args:
        target_dir: directory where weights will be saved
    Returns:
        Path to the expected .pt file location (for documentation)
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / "contrail_resunet34.pt"
    if dest.exists():
        logger.info("Weights already present: %s", dest)
        return dest

    logger.warning(
        "SurfDrive requires browser authentication — automated download not supported.\n"
        "Manual steps:\n"
        "  1. Open https://surfdrive.surf.nl/files/index.php/s/n1b0L2qfu2PZ6d3\n"
        "  2. Download the .pt weights file\n"
        "  3. Copy to: %s", dest
    )
    return dest


# ── Sample image download (for smoke-testing without a camera) ─────────────────

def make_synthetic_contrail_image(dest: Path = Path(__file__).parent / "sample_synthetic.jpg",
                                   size: tuple[int, int] = (640, 480)) -> Path:
    """
    Generates a realistic synthetic sky + contrail image using OpenCV.

    Avoids network dependency — useful for CI and offline testing.  The image
    has a blue-sky gradient in the upper half and two crossing bright contrail
    lines, which the OpenCV heuristic backend can detect.

    For real contrail images (GVCCS ground-camera dataset, 24 228 frames):
        https://zenodo.org/records/15743988  (free Zenodo account, 2.1 GB)
    """
    w, h = size
    img = np.zeros((h, w, 3), dtype=np.uint8)

    # Sky gradient: deep blue at top → lighter blue-grey at horizon
    for y in range(h):
        t = y / h
        b = int(180 - t * 60)
        g = int(120 + t * 40)
        r = int(80  + t * 60)
        img[y, :] = (b, g, r)   # BGR

    # Add slight noise to simulate atmospheric haze
    noise = np.random.randint(-8, 8, img.shape, dtype=np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    # Draw two crossing contrail lines (bright, slightly blurred)
    cv2.line(img, (30, 60),  (w - 30, 140), (245, 245, 255), 5)
    cv2.line(img, (80, 180), (w - 80, 40),  (240, 242, 255), 4)
    # Gaussian blur to soften edges (contrails diffuse over time)
    img = cv2.GaussianBlur(img, (3, 3), 0)

    cv2.imwrite(str(dest), img)
    logger.info("Synthetic contrail image saved → %s", dest)
    return dest


# ── ONNX export (run once after fine-tuning) ──────────────────────────────────

def export_to_onnx(pt_path: Path = PT_PATH, onnx_path: Path = ONNX_PATH) -> None:
    """
    Exports a trained PyTorch checkpoint to ONNX for fast ARM inference.
    Run this once on a workstation after fine-tuning on GVCCS data.

    Example fine-tune command (requires GVCCS dataset):
        python train.py --data /path/to/gvccs --epochs 20 --out weights/contrail_resunet34.pt
    """
    import torch

    model = _build_resunet34()
    model.load_state_dict(torch.load(str(pt_path), map_location="cpu"))
    model.eval()

    dummy = torch.randn(1, 3, *INPUT_SIZE)
    torch.onnx.export(
        model, dummy, str(onnx_path),
        input_names=["image"],
        output_names=["logits"],
        dynamic_axes={"image": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=17,
    )
    logger.info("Exported ONNX model to %s", onnx_path)


# ── CLI / demo ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, sys

    ap = argparse.ArgumentParser(description="Contrail detection inference")
    ap.add_argument("image", nargs="?", help="Path to image file (omit for webcam demo)")
    ap.add_argument("--download-weights", action="store_true",
                    help="Print instructions for downloading pre-trained weights")
    ap.add_argument("--download-sample", action="store_true",
                    help="Download one sample frame from GVCCS for smoke-testing")
    ap.add_argument("--export-onnx", action="store_true", help="Export PyTorch → ONNX")
    ap.add_argument("--show", action="store_true", help="Display result with OpenCV")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.download_weights:
        download_weights()
        sys.exit(0)

    if args.download_sample:
        make_synthetic_contrail_image()
        sys.exit(0)

    if args.export_onnx:
        export_to_onnx()
        sys.exit(0)

    detector = ContrailDetector()

    if args.image:
        frame = cv2.imread(args.image)
        if frame is None:
            print(f"Cannot read image: {args.image}")
            sys.exit(1)
    else:
        # Webcam demo — press q to quit
        cap = cv2.VideoCapture(0)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            print("No webcam frame captured")
            sys.exit(1)

    result = detector.detect(frame)
    print(f"Contrail detected : {result.contrail_detected}")
    print(f"Confidence        : {result.confidence:.3f}")
    print(f"Pixel ratio       : {result.pixel_ratio:.4%}")
    print(f"Backend           : {result.backend}")

    if args.show:
        overlay = frame.copy()
        overlay[result.mask > 0] = [0, 200, 255]   # cyan overlay on contrail pixels
        cv2.addWeighted(overlay, 0.4, frame, 0.6, 0, frame)
        label = f"Contrail: {'YES' if result.contrail_detected else 'NO'}  conf={result.confidence:.2f}"
        cv2.putText(frame, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                    (0, 200, 255) if result.contrail_detected else (100, 100, 100), 2)
        cv2.imshow("COAV contrail detection", frame)
        cv2.waitKey(0)
        cv2.destroyAllWindows()
