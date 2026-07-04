"""
Contrail detection via semantic segmentation.

Architecture : U-Net + EfficientNet-B2 (7M params)
Training data: GVCCS — 24,228 frames from EUROCONTROL MUAC ground cameras, Brétigny-sur-Orge
               (Zenodo: 10.5281/zenodo.15743988)
Best val Dice: 0.8085 (epoch 59 of 60, calibrated threshold 0.45, TTA +0.5-1%)

Inference    : PyTorch (GPU/CPU), ONNX Runtime (ARM — Raspberry Pi, Jetson)
               Falls back to OpenCV heuristic if neither is available

Usage:
    detector = ContrailDetector()                      # default: t=0.45, no TTA
    detector = ContrailDetector(threshold=0.45, use_tta=True)  # TTA for offline eval
    result   = detector.detect(frame_bgr)
    print(result.contrail_detected, result.confidence)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ── Model config ───────────────────────────────────────────────────────────────
MODEL_DIR = Path(__file__).parent / "weights"
PT_PATH   = MODEL_DIR / "contrail_unet.pt"    # U-Net EfficientNet-B2 weights
ONNX_PATH = MODEL_DIR / "contrail_unet.onnx"  # exported after training

ENCODER    = "efficientnet-b2"
INPUT_SIZE = (512, 512)
PIXEL_MEAN = [0.485, 0.456, 0.406]
PIXEL_STD  = [0.229, 0.224, 0.225]

# Calibrated on val set after 60-epoch training — optimal F1/Dice trade-off
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

        # Allow override of default weight path
        if weights_path is not None:
            global PT_PATH
            PT_PATH = Path(weights_path)

        self._init_model()

    # ── Initialisation ─────────────────────────────────────────────────────────

    def _init_model(self) -> None:
        if ONNX_PATH.exists():
            self._load_onnx()
        elif PT_PATH.exists():
            self._load_pytorch()
        else:
            logger.warning(
                "No weights found in %s — OpenCV heuristic fallback active. "
                "Copy contrail_unet.pt from HuggingFace to %s.",
                MODEL_DIR, PT_PATH,
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
            self._model = _build_unet_b2()
            state = torch.load(str(PT_PATH), map_location="cpu", weights_only=True)
            # checkpoint_last.pt wraps state in 'model_state'; best .pt is plain state_dict
            if isinstance(state, dict) and "model_state" in state:
                state = state["model_state"]
            self._model.load_state_dict(state)
            self._model.eval()
            self._backend = "pytorch"
            logger.info("ContrailDetector: PyTorch backend (%s)", PT_PATH.name)
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
        """Average sigmoid probabilities over 4 flip augmentations."""
        torch = self._torch
        variants = [
            inp,
            torch.flip(inp, [-1]),       # H-flip
            torch.flip(inp, [-2]),       # V-flip
            torch.flip(inp, [-1, -2]),   # HV-flip
        ]
        preds = []
        with torch.no_grad():
            for v in variants:
                p = torch.sigmoid(self._model(v))[0, 0]
                preds.append(p)
        # Undo flips so spatial positions align before averaging
        preds[1] = torch.flip(preds[1], [-1])
        preds[2] = torch.flip(preds[2], [-2])
        preds[3] = torch.flip(preds[3], [-1, -2])
        return torch.stack(preds).mean(0).numpy()

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
    state = torch.load(str(pt_path), map_location="cpu", weights_only=True)
    if isinstance(state, dict) and "model_state" in state:
        state = state["model_state"]
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
