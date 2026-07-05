"""
Contrail detection via semantic segmentation.

Architecture : U-Net + EfficientNet-B2 (7M params)
Training data: GVCCS — 24,228 frames from EUROCONTROL MUAC ground cameras, Brétigny-sur-Orge
               (Zenodo: 10.5281/zenodo.15743988)
Best val Dice: 0.8394 (global, calibrated, WR-2 epoch 88 of 90, t=0.50).
               Plateaued at ~0.83-0.84 through WR-3 + SWA (epoch 120); deployed weights
               are the epoch-116 EMA checkpoint (per-batch 0.8343, not re-calibrated).
               See edge-pi/TRAINING_LOG.md.

Inference    : PyTorch (GPU/CPU), ONNX Runtime (ARM — Raspberry Pi, Jetson)
               Falls back to OpenCV heuristic if neither is available

Usage:
    detector = ContrailDetector()                      # default: t=0.45, no TTA
    detector = ContrailDetector(threshold=0.45, use_tta=True)  # TTA for offline eval
    result   = detector.detect(frame_bgr)
    print(result.contrail_detected, result.confidence)
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Ensure the weights-resolution log (path/size/sha256/backend) is visible even
# when the importing process (e.g. edge-emulator/emulator.py) never calls
# logging.basicConfig() itself. No-op if the root logger already has handlers.
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# ── Model config ───────────────────────────────────────────────────────────────
MODEL_DIR = Path(__file__).parent / "weights"
PT_PATH   = MODEL_DIR / "contrail_unet.pt"    # U-Net EfficientNet-B2 weights
ONNX_PATH = MODEL_DIR / "contrail_unet.onnx"  # exported after training

# repo_root/edge-pi/python/inference.py -> repo_root
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Auto-discovery fallback order when PT_PATH (weights/contrail_unet.pt) is
# missing — checked in this order, first existing file wins:
#   1. WEIGHTS_PATH env var (explicit override)
#   2. edge-pi/data/contrail_unet_best.pt  — plain state_dict, best val Dice
#   3. edge-pi/data/checkpoint_last.pt     — full checkpoint dict (epoch/best_dice/model_state)
_FALLBACK_DATA_DIR = _REPO_ROOT / "edge-pi" / "data"
FALLBACK_WEIGHTS_CANDIDATES = [
    _FALLBACK_DATA_DIR / "contrail_unet_best.pt",
    _FALLBACK_DATA_DIR / "checkpoint_last.pt",
]

ENCODER    = "efficientnet-b2"
INPUT_SIZE = (512, 512)
PIXEL_MEAN = [0.485, 0.456, 0.406]
PIXEL_STD  = [0.229, 0.224, 0.225]

# WR-2 val calibration favoured t=0.50 (global Dice 0.8394); the current epoch-116 EMA
# weights were not re-calibrated. Kept at 0.45 (slightly more sensitive) — conservative
# default that also keeps demo masks clearly visible.
DEFAULT_THRESHOLD   = 0.45
PIXEL_RATIO_THRESHOLD = 0.001   # 0.1% of frame (~250 pixels at 512×512)


@dataclass
class DetectionResult:
    contrail_detected: bool
    confidence: float                      # mean prob in detected region (0–1)
    pixel_ratio: float                     # fraction of frame covered by contrail mask
    mask: np.ndarray = field(repr=False)   # binary mask, original frame resolution
    backend: str = "unknown"              # "pytorch" | "onnx" | "opencv"
    tta: bool = False


class ContrailDetector:
    """
    Loads once, detects on every frame.  Thread-safe (ONNX session is stateless).

    Priority:
      1. ONNX Runtime  — fastest on ARM (~50-150 ms/frame)
      2. PyTorch       — if onnxruntime not installed
      3. OpenCV        — pure-heuristic fallback, no learned weights

    TTA (Test-Time Augmentation):
      Averages predictions from 4 orientations (original + H-flip + V-flip + HV-flip).
      Adds ~5-10% latency, gains ~0.5-1% Dice.  Recommended for offline evaluation,
      optional for real-time 1 FPS deployment.
    """

    def __init__(
        self,
        weights_path: Path | str | None = None,
        threshold: float = DEFAULT_THRESHOLD,
        use_tta: bool = False,
    ):
        self.threshold = threshold
        self.use_tta   = use_tta
        self._session  = None
        self._model    = None
        self._backend  = "opencv"
        # Resolved .pt path for this instance — never mutates the module-level
        # PT_PATH default, so instances/tests don't leak state into each other.
        self._pt_path: Path | None = None
        self._explicit_weights_path = Path(weights_path) if weights_path is not None else None

        self._init_model()
        logger.info("ContrailDetector ready — final backend=%s", self._backend)

    # ── Initialisation ─────────────────────────────────────────────────────────

    def _resolve_pt_path(self) -> Path | None:
        """
        Resolve which .pt weights file to load.

        Priority: explicit weights_path (constructor arg) > default
        MODEL_DIR/contrail_unet.pt > WEIGHTS_PATH env > edge-pi/data/
        contrail_unet_best.pt > edge-pi/data/checkpoint_last.pt.
        """
        if self._explicit_weights_path is not None and self._explicit_weights_path.exists():
            return self._explicit_weights_path
        if PT_PATH.exists():
            return PT_PATH
        if self._explicit_weights_path is not None:
            # Caller explicitly asked for a path and it doesn't exist —
            # still fall through to auto-discovery below as a last resort.
            logger.warning("Explicit weights_path %s not found — trying auto-discovery",
                            self._explicit_weights_path)

        env_path = os.getenv("WEIGHTS_PATH")
        candidates = ([Path(env_path)] if env_path else []) + FALLBACK_WEIGHTS_CANDIDATES
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _init_model(self) -> None:
        if ONNX_PATH.exists():
            self._load_onnx()
            return

        resolved = self._resolve_pt_path()
        if resolved is not None:
            self._pt_path = resolved
            self._load_pytorch()
        else:
            logger.warning(
                "No weights found in %s or fallback locations (%s) — "
                "OpenCV heuristic fallback active. Copy contrail_unet.pt "
                "or set WEIGHTS_PATH.",
                MODEL_DIR, ", ".join(str(c) for c in FALLBACK_WEIGHTS_CANDIDATES),
            )

    def _load_onnx(self) -> None:
        try:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 2
            self._session = ort.InferenceSession(
                str(ONNX_PATH),
                sess_options=opts,
                providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            )
            self._backend = "onnx"
            logger.info("ContrailDetector: ONNX backend (%s)", ONNX_PATH.name)
        except ImportError:
            logger.warning("onnxruntime not installed — trying PyTorch backend")
            self._load_pytorch()

    def _load_pytorch(self) -> None:
        try:
            import torch
            self._torch = torch

            pt_path = self._pt_path
            size_bytes = pt_path.stat().st_size
            sha12 = _sha256_prefix(pt_path)
            logger.info(
                "Loading PyTorch weights: path=%s size=%.1fMB sha256=%s",
                pt_path, size_bytes / 1e6, sha12,
            )

            self._model = _build_unet_b2()
            raw = torch.load(str(pt_path), map_location="cpu", weights_only=True)
            state, meta = _extract_state_dict(raw)
            if meta:
                logger.info(
                    "Checkpoint metadata: epoch=%s best_dice=%s",
                    meta.get("epoch"), meta.get("best_dice"),
                )
            self._model.load_state_dict(state)
            self._model.eval()
            self._backend = "pytorch"
            logger.info("ContrailDetector: PyTorch backend (%s)", pt_path.name)
        except ImportError:
            logger.warning("torch not installed — using OpenCV heuristic fallback")

    # ── Public API ─────────────────────────────────────────────────────────────

    def detect(self, frame_bgr: np.ndarray) -> DetectionResult:
        """
        Run contrail segmentation on a single BGR frame (OpenCV / picamera2).

        Args:
            frame_bgr: numpy array (H, W, 3) uint8

        Returns:
            DetectionResult with binary mask at original frame resolution
        """
        if self._backend == "onnx":
            return self._detect_onnx(frame_bgr)
        if self._backend == "pytorch":
            return self._detect_pytorch(frame_bgr)
        return self._detect_opencv(frame_bgr)

    # ── ONNX inference ─────────────────────────────────────────────────────────

    def _detect_onnx(self, frame_bgr: np.ndarray) -> DetectionResult:
        tensor = _preprocess(frame_bgr)
        name   = self._session.get_inputs()[0].name
        logits = self._session.run(None, {name: tensor})[0]
        prob   = 1.0 / (1.0 + np.exp(-logits[0, 0]))   # sigmoid
        return self._postprocess(prob, frame_bgr.shape[:2], "onnx")

    # ── PyTorch inference ──────────────────────────────────────────────────────

    def _detect_pytorch(self, frame_bgr: np.ndarray) -> DetectionResult:
        torch = self._torch
        inp   = torch.from_numpy(_preprocess(frame_bgr))  # (1,3,512,512)

        if self.use_tta:
            prob = self._tta_prob(inp)
        else:
            with torch.no_grad():
                prob = torch.sigmoid(self._model(inp))[0, 0].numpy()

        return self._postprocess(prob, frame_bgr.shape[:2], "pytorch")

    def _tta_prob(self, inp):
        """H-flip only TTA: average of original + horizontal flip.

        V-flip and HV-flip hurt for ground-camera contrails: sky is always at top,
        so vertically-flipped images are out-of-distribution. H-flip is safe because
        contrails are symmetric under left/right reflection.
        """
        torch = self._torch
        with torch.no_grad():
            p_orig  = torch.sigmoid(self._model(inp))[0, 0]
            p_hflip = torch.sigmoid(self._model(torch.flip(inp, [-1])))[0, 0]
            p_hflip = torch.flip(p_hflip, [-1])   # undo flip before averaging
        return ((p_orig + p_hflip) / 2).numpy()

    # ── OpenCV heuristic fallback ──────────────────────────────────────────────

    def _detect_opencv(self, frame_bgr: np.ndarray) -> DetectionResult:
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        sky  = gray[:gray.shape[0] // 2, :]
        _, bright = cv2.threshold(sky, 200, 255, cv2.THRESH_BINARY)
        edges = cv2.Canny(bright, 50, 150)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=80,
                                minLineLength=80, maxLineGap=20)
        mask = np.zeros(sky.shape[:2], dtype=np.float32)
        if lines is not None:
            for x1, y1, x2, y2 in lines.reshape(-1, 4):
                cv2.line(mask, (int(x1), int(y1)), (int(x2), int(y2)), 1.0, 8)
        pixel_ratio = float(mask.sum()) / mask.size
        confidence  = min(pixel_ratio * 20, 0.85)
        detected    = pixel_ratio > PIXEL_RATIO_THRESHOLD
        full_mask = np.zeros(frame_bgr.shape[:2], dtype=np.uint8)
        full_mask[:sky.shape[0]] = (mask * 255).astype(np.uint8)
        return DetectionResult(detected, confidence, pixel_ratio, full_mask, "opencv")

    # ── Shared post-processing ─────────────────────────────────────────────────

    def _postprocess(
        self, prob: np.ndarray, orig_hw: tuple[int, int], backend: str
    ) -> DetectionResult:
        mask_512  = (prob > self.threshold).astype(np.uint8) * 255
        mask_orig = cv2.resize(mask_512, (orig_hw[1], orig_hw[0]),
                               interpolation=cv2.INTER_NEAREST)
        pixel_ratio = float((mask_orig > 0).sum()) / mask_orig.size
        if pixel_ratio > 0:
            confidence = float(prob[prob > self.threshold].mean())
        else:
            confidence = float(prob.mean())
        detected = pixel_ratio > PIXEL_RATIO_THRESHOLD
        return DetectionResult(detected, round(confidence, 3), round(pixel_ratio, 6),
                               mask_orig, backend, tta=self.use_tta)


def _sha256_prefix(path: Path, n: int = 12, chunk_size: int = 1 << 20) -> str:
    """First `n` hex chars of the file's sha256 — cheap fingerprint for logs."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()[:n]


def _extract_state_dict(raw: dict) -> tuple[dict, dict | None]:
    """
    Accepts either a plain state_dict (contrail_unet_best.pt) or a checkpoint
    dict (checkpoint_last.pt: epoch/encoder/model_state/best_dice/history).

    Returns (state_dict, checkpoint_meta_or_None).
    """
    if isinstance(raw, dict):
        for key in ("model_state", "state_dict"):
            if key in raw:
                meta = {k: v for k, v in raw.items() if k != key}
                return raw[key], meta
    return raw, None


# ── Model architecture ─────────────────────────────────────────────────────────

def _build_unet_b2():
    """U-Net + EfficientNet-B2 — matches training notebook architecture."""
    try:
        import segmentation_models_pytorch as smp
        return smp.Unet(
            encoder_name="efficientnet-b2",
            encoder_weights=None,
            in_channels=3,
            classes=1,
            activation=None,
        )
    except ImportError as exc:
        raise RuntimeError(
            "segmentation-models-pytorch required. "
            "Install with: pip install segmentation-models-pytorch"
        ) from exc


# ── Pre-processing ─────────────────────────────────────────────────────────────

def _preprocess(frame_bgr: np.ndarray) -> np.ndarray:
    """BGR frame → normalised (1, 3, 512, 512) float32 NCHW array."""
    rgb    = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    sized  = cv2.resize(rgb, INPUT_SIZE)
    normed = (sized.astype(np.float32) / 255.0 - PIXEL_MEAN) / PIXEL_STD
    return normed.transpose(2, 0, 1)[np.newaxis].astype(np.float32)


# ── ONNX export ────────────────────────────────────────────────────────────────

def export_to_onnx(
    pt_path: Path = PT_PATH,
    onnx_path: Path = ONNX_PATH,
) -> None:
    """Export trained PyTorch checkpoint to ONNX for ARM deployment."""
    import torch
    model = _build_unet_b2()
    raw = torch.load(str(pt_path), map_location="cpu", weights_only=True)
    state, _meta = _extract_state_dict(raw)
    model.load_state_dict(state)
    model.eval()
    dummy = torch.randn(1, 3, *INPUT_SIZE)
    torch.onnx.export(
        model, dummy, str(onnx_path),
        input_names=["image"],
        output_names=["logits"],
        dynamic_axes={"image": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=17,
    )
    logger.info("ONNX model exported → %s", onnx_path)


# ── Synthetic test image ───────────────────────────────────────────────────────

def make_synthetic_contrail_image(
    dest: Path = Path(__file__).parent / "sample_synthetic.jpg",
    size: tuple[int, int] = (640, 480),
) -> Path:
    """Generate a synthetic sky + contrail image for smoke-testing without a camera."""
    w, h = size
    img  = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        t = y / h
        img[y, :] = (int(180 - t * 60), int(120 + t * 40), int(80 + t * 60))
    noise = np.random.randint(-8, 8, img.shape, dtype=np.int16)
    img   = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    cv2.line(img, (30, 60),  (w - 30, 140), (245, 245, 255), 5)
    cv2.line(img, (80, 180), (w - 80, 40),  (240, 242, 255), 4)
    img = cv2.GaussianBlur(img, (3, 3), 0)
    cv2.imwrite(str(dest), img)
    logger.info("Synthetic image → %s", dest)
    return dest


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, sys

    ap = argparse.ArgumentParser(description="Contrail detection — U-Net EfficientNet-B2")
    ap.add_argument("image", nargs="?", help="Image path (omit for webcam)")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                    help=f"Sigmoid threshold (default: {DEFAULT_THRESHOLD})")
    ap.add_argument("--tta", action="store_true",
                    help="Enable Test-Time Augmentation (4× orientations averaged)")
    ap.add_argument("--export-onnx", action="store_true", help="Export PyTorch → ONNX")
    ap.add_argument("--synthetic", action="store_true",
                    help="Generate a synthetic contrail image for smoke-testing")
    ap.add_argument("--show", action="store_true", help="Display result with OpenCV")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.export_onnx:
        export_to_onnx()
        sys.exit(0)

    if args.synthetic:
        make_synthetic_contrail_image()
        sys.exit(0)

    detector = ContrailDetector(threshold=args.threshold, use_tta=args.tta)

    if args.image:
        frame = cv2.imread(args.image)
        if frame is None:
            print(f"Cannot read: {args.image}")
            sys.exit(1)
    else:
        cap = cv2.VideoCapture(0)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            print("No webcam frame")
            sys.exit(1)

    result = detector.detect(frame)
    print(f"Contrail detected : {result.contrail_detected}")
    print(f"Confidence        : {result.confidence:.3f}")
    print(f"Pixel ratio       : {result.pixel_ratio:.4%}")
    print(f"Backend           : {result.backend}  (TTA={result.tta})")
    print(f"Threshold         : {args.threshold:.2f}")

    if args.show:
        overlay = frame.copy()
        overlay[result.mask > 0] = [0, 200, 255]
        cv2.addWeighted(overlay, 0.4, frame, 0.6, 0, frame)
        label = f"{'YES' if result.contrail_detected else 'NO'}  conf={result.confidence:.2f}  t={args.threshold}"
        cv2.putText(frame, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                    (0, 200, 255) if result.contrail_detected else (100, 100, 100), 2)
        cv2.imshow("COAV contrail detection", frame)
        cv2.waitKey(0)
        cv2.destroyAllWindows()
