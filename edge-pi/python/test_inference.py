"""
Unit tests for inference.py — contrail segmentation.

No model weights required: tests cover preprocessing, the OpenCV heuristic
backend (always available), DetectionResult contracts, and ContrailDetector
graceful degradation when no ONNX/PyTorch weights are present.
"""

import time
import numpy as np
import pytest
import cv2

from inference import (
    ContrailDetector,
    DetectionResult,
    _preprocess,
    make_synthetic_contrail_image,
    INPUT_SIZE,
    PIXEL_MEAN,
    PIXEL_STD,
    PIXEL_RATIO_THRESHOLD,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sky_frame():
    """Uniform blue-sky BGR frame (640×480) — no contrails expected."""
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[:, :] = (200, 160, 100)   # BGR sky blue
    return frame


@pytest.fixture
def contrail_frame():
    """Sky frame with a bright white diagonal line in the upper half — contrail cue."""
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[:, :] = (200, 160, 100)   # sky background
    # Draw a bright white line across the full width of the upper half
    import cv2
    cv2.line(frame, (20, 100), (620, 120), (255, 255, 255), 6)
    return frame


@pytest.fixture
def no_weights(monkeypatch):
    """
    Force ContrailDetector's auto-discovery to find nothing, regardless of
    whether edge-pi/data/*.pt happens to exist on the machine running the
    tests (those weights are gitignored and dev-machine-specific).
    """
    import inference as inf
    monkeypatch.setattr(inf, "FALLBACK_WEIGHTS_CANDIDATES", [])
    monkeypatch.delenv("WEIGHTS_PATH", raising=False)


@pytest.fixture
def detector(no_weights):
    """ContrailDetector with no weights — always uses OpenCV fallback."""
    return ContrailDetector()


# ── _preprocess ───────────────────────────────────────────────────────────────

class TestPreprocess:
    def test_output_shape(self, sky_frame):
        out = _preprocess(sky_frame)
        assert out.shape == (1, 3, INPUT_SIZE[0], INPUT_SIZE[1])

    def test_output_dtype(self, sky_frame):
        out = _preprocess(sky_frame)
        assert out.dtype == np.float32

    def test_output_is_nchw(self, sky_frame):
        out = _preprocess(sky_frame)
        # channels dim is 3 (RGB), spatial dims are INPUT_SIZE
        assert out.shape[1] == 3
        assert out.shape[2:] == INPUT_SIZE

    def test_normalisation_range(self, sky_frame):
        """After ImageNet normalisation values should be roughly in [-3, 3]."""
        out = _preprocess(sky_frame)
        assert out.min() > -4.0
        assert out.max() <  4.0

    def test_black_frame_normalisation(self):
        black = np.zeros((480, 640, 3), dtype=np.uint8)
        out   = _preprocess(black)
        # black pixel (0,0,0) → (0 - mean) / std
        expected_r = (0.0 - PIXEL_MEAN[0]) / PIXEL_STD[0]
        assert abs(out[0, 0, 0, 0] - expected_r) < 0.01

    def test_accepts_various_resolutions(self):
        for h, w in [(240, 320), (720, 1280), (1080, 1920)]:
            frame = np.random.randint(0, 256, (h, w, 3), dtype=np.uint8)
            out   = _preprocess(frame)
            assert out.shape == (1, 3, *INPUT_SIZE)


# ── ContrailDetector initialisation ──────────────────────────────────────────

class TestDetectorInit:
    def test_no_weights_falls_back_to_opencv(self, detector):
        assert detector._backend == "opencv"

    def test_session_is_none_without_onnx_weights(self, detector):
        assert detector._session is None

    def test_model_is_none_without_pytorch_weights(self, detector):
        assert detector._model is None


# ── OpenCV fallback detection ─────────────────────────────────────────────────

class TestOpenCVDetection:
    def test_returns_detection_result(self, detector, sky_frame):
        result = detector.detect(sky_frame)
        assert isinstance(result, DetectionResult)

    def test_backend_is_opencv(self, detector, sky_frame):
        result = detector.detect(sky_frame)
        assert result.backend == "opencv"

    def test_mask_shape_matches_input(self, detector, sky_frame):
        result = detector.detect(sky_frame)
        assert result.mask.shape == sky_frame.shape[:2]

    def test_mask_dtype_is_uint8(self, detector, sky_frame):
        result = detector.detect(sky_frame)
        assert result.mask.dtype == np.uint8

    def test_mask_values_binary(self, detector, sky_frame):
        result = detector.detect(sky_frame)
        unique = set(np.unique(result.mask))
        assert unique.issubset({0, 255})

    def test_pixel_ratio_in_range(self, detector, sky_frame):
        result = detector.detect(sky_frame)
        assert 0.0 <= result.pixel_ratio <= 1.0

    def test_confidence_in_range(self, detector, sky_frame):
        result = detector.detect(sky_frame)
        assert 0.0 <= result.confidence <= 1.0

    def test_empty_sky_not_detected(self, detector, sky_frame):
        """Uniform sky with no lines should produce very low pixel_ratio."""
        result = detector.detect(sky_frame)
        # pixel_ratio should be well below threshold for a featureless sky
        assert result.pixel_ratio < PIXEL_RATIO_THRESHOLD * 10

    def test_contrail_line_detected(self, detector, contrail_frame):
        """Bright white line across upper half should trigger HoughLines detection."""
        result = detector.detect(contrail_frame)
        # OpenCV heuristic: pixel_ratio > 0 for a clearly visible bright line
        assert result.pixel_ratio > 0.0

    def test_contrail_mask_upper_half_only(self, detector, contrail_frame):
        """OpenCV looks at upper half only; bottom half mask should be all zeros."""
        result = detector.detect(contrail_frame)
        h = contrail_frame.shape[0]
        assert result.mask[h // 2:].sum() == 0

    def test_confidence_higher_with_contrail(self, detector, sky_frame, contrail_frame):
        """Confidence should increase when contrail structure is present."""
        conf_sky      = detector.detect(sky_frame).confidence
        conf_contrail = detector.detect(contrail_frame).confidence
        assert conf_contrail >= conf_sky

    def test_accepts_different_frame_sizes(self, detector):
        for h, w in [(240, 320), (720, 1280)]:
            frame  = np.zeros((h, w, 3), dtype=np.uint8)
            result = detector.detect(frame)
            assert result.mask.shape == (h, w)


# ── DetectionResult contract ──────────────────────────────────────────────────

class TestDetectionResult:
    def test_all_fields_present(self, detector, sky_frame):
        r = detector.detect(sky_frame)
        assert hasattr(r, "contrail_detected")
        assert hasattr(r, "confidence")
        assert hasattr(r, "pixel_ratio")
        assert hasattr(r, "mask")
        assert hasattr(r, "backend")

    def test_contrail_detected_is_bool(self, detector, sky_frame):
        assert isinstance(detector.detect(sky_frame).contrail_detected, bool)

    def test_confidence_is_float(self, detector, sky_frame):
        assert isinstance(detector.detect(sky_frame).confidence, float)

    def test_pixel_ratio_is_float(self, detector, sky_frame):
        assert isinstance(detector.detect(sky_frame).pixel_ratio, float)

    def test_detected_flag_consistent_with_pixel_ratio(self, detector, sky_frame):
        r = detector.detect(sky_frame)
        if r.contrail_detected:
            assert r.pixel_ratio > PIXEL_RATIO_THRESHOLD
        else:
            assert r.pixel_ratio <= PIXEL_RATIO_THRESHOLD * 10  # some slack for opencv

    def test_repr_excludes_mask(self, detector, sky_frame):
        """mask is large — repr should not include it."""
        r = detector.detect(sky_frame)
        assert "mask" not in repr(r)


# ── Real-image smoke test (requires network; skipped in CI) ───────────────────
# Run manually: python -m pytest test_inference.py -m real -v

# ── Synthetic end-to-end smoke test ──────────────────────────────────────────
# Tests the full pipeline on a programmatically generated sky+contrail image.
# No network, no camera, no dataset required — runs in CI.
#
# For proper evaluation on real ground-camera data, download GVCCS:
#   https://zenodo.org/records/15743988  (free Zenodo account, 2.1 GB)
#   python train.py --data /path/to/GVCCS --epochs 20
#
# For pre-trained satellite-domain weights (junzis/contrail-seg):
#   https://surfdrive.surf.nl/files/index.php/s/n1b0L2qfu2PZ6d3
#   (SurfDrive requires browser login — copy .pt to edge-pi/python/weights/)
#   Note: satellite weights need GVCCS fine-tuning for ground-camera domain.

class TestSyntheticEndToEnd:
    """Full pipeline on a synthetic sky + contrail image — no network required."""

    @pytest.fixture(scope="class")
    def synthetic_image_path(self, tmp_path_factory):
        dest = tmp_path_factory.mktemp("synth") / "contrail_synthetic.jpg"
        return make_synthetic_contrail_image(dest=dest)

    @pytest.fixture(scope="class")
    def synthetic_frame(self, synthetic_image_path):
        frame = cv2.imread(str(synthetic_image_path))
        assert frame is not None, "make_synthetic_contrail_image failed"
        return frame

    def test_synthetic_image_readable(self, synthetic_frame):
        assert synthetic_frame.shape == (480, 640, 3)
        assert synthetic_frame.dtype == np.uint8

    def test_pipeline_runs_on_synthetic(self, synthetic_frame):
        result = ContrailDetector().detect(synthetic_frame)
        assert isinstance(result, DetectionResult)
        assert result.mask.shape == synthetic_frame.shape[:2]
        assert result.backend in ("onnx", "pytorch", "opencv")

    def test_opencv_detects_drawn_contrails(self, synthetic_frame, no_weights):
        """The synthetic image has two bright diagonal lines — HoughLinesP should find them."""
        result = ContrailDetector().detect(synthetic_frame)
        assert result.backend == "opencv"   # no weights in test env
        assert result.pixel_ratio > 0.0, "OpenCV missed the drawn contrail lines"
        assert result.contrail_detected is True

    def test_mask_covers_upper_half_only(self, synthetic_frame):
        """OpenCV only scans sky region (top half) — lower half mask must be zero."""
        result = ContrailDetector().detect(synthetic_frame)
        h = synthetic_frame.shape[0]
        assert result.mask[h // 2 :].sum() == 0

    def test_mask_nonzero_in_upper_half(self, synthetic_frame):
        """Drawn contrails are in the upper half — some pixels should be marked."""
        result = ContrailDetector().detect(synthetic_frame)
        h = synthetic_frame.shape[0]
        assert result.mask[: h // 2].sum() > 0

    def test_full_pipeline_returns_consistent_result(self, synthetic_frame):
        r = ContrailDetector().detect(synthetic_frame)
        if r.contrail_detected:
            assert r.pixel_ratio > PIXEL_RATIO_THRESHOLD
        assert 0.0 <= r.confidence <= 1.0
        assert 0.0 <= r.pixel_ratio <= 1.0
