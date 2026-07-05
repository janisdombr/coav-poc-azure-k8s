"""
Day 11 / P1 — camera verification channel tests.

Covers:
  * CameraProducer in isolation (frames_dir -> valid EdgeVisionAI payloads)
  * Connected-component contrail counting
  * Temporal delta (repeated component -> new_contrail_count == 0)
  * OpenCV-fallback operation without model weights (no torch required)
  * EdgeVisionAI Pydantic negative cases (OWASP A03 outbound gate)
  * prepare_val_frames.val_indices — deterministic seed=42 split, no leakage
"""

import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest
from pydantic import ValidationError

from emulator import CameraProducer, EdgeVisionAI, CAMERAS
from prepare_val_frames import val_indices, SEED, VAL_FRACTION

HERE = Path(__file__).resolve().parent


# ── Helpers ───────────────────────────────────────────────────────────────────

def sky_frame(lines: list[tuple[int, int, int, int]], h: int = 480, w: int = 640):
    """Dark sky frame with bright straight 'contrail' lines in the top half."""
    img = np.full((h, w, 3), 90, dtype=np.uint8)
    for x1, y1, x2, y2 in lines:
        cv2.line(img, (x1, y1), (x2, y2), (255, 255, 255), 5)
    return img


@pytest.fixture()
def producer(tmp_path):
    """Producer over an empty frames dir (synthetic fallback), forced onto the
    built-in OpenCV heuristic so tests are deterministic and weight-free."""
    p = CameraProducer(frames_dir=tmp_path)
    p.detector = None          # built-in heuristic — no U-Net, no torch
    return p


# ── CameraProducer: channel shape ─────────────────────────────────────────────

def test_produce_emits_one_event_per_camera(producer):
    events = producer.produce()
    assert len(events) == len(CAMERAS) == 4
    assert [e["camera_id"] for e in events] == [c["id"] for c in CAMERAS]


def test_produce_events_are_camera_keyed_without_flight_id(producer):
    for e in producer.produce():
        assert e["message_type"] == "EDGE_VISION_AI"
        assert "flight_id" not in e          # decoupled channel (P1)
        assert "latitude" not in e
        assert "heading" not in e


def test_produce_events_pass_pydantic_validation(producer):
    """Every emitted payload must satisfy the outbound schema (OWASP A03)."""
    for e in producer.produce():
        EdgeVisionAI(**e)


def test_produce_multiple_ticks_cycles_frames(producer):
    refs_t1 = {e["camera_id"]: e["frame_ref"] for e in producer.produce()}
    refs_t2 = {e["camera_id"]: e["frame_ref"] for e in producer.produce()}
    # 8 synthetic frames over 4 cameras -> each camera has 2 frames to cycle
    assert refs_t1 != refs_t2


def test_frames_dir_manifest_loading(tmp_path):
    """frames_dir with manifest.json → producer reads real frames from disk."""
    for i in range(2):
        cv2.imwrite(str(tmp_path / f"frame_{i}.jpg"),
                    sky_frame([(50, 60 + 90 * i, 590, 70 + 90 * i)]))
    manifest = {"frames": [
        {"frame_ref": f"gvccs_val_{i:05d}", "file": f"frame_{i}.jpg"}
        for i in range(2)
    ]}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    p = CameraProducer(frames_dir=tmp_path)
    p.detector = None
    assert len(p._frames) == 2
    assert all(f["path"] is not None for f in p._frames)

    events = p.produce()
    assert len(events) > 0
    for e in events:
        EdgeVisionAI(**e)
        assert e["frame_ref"].startswith("gvccs_val_")


def test_missing_frames_dir_falls_back_to_synthetic(tmp_path):
    p = CameraProducer(frames_dir=tmp_path / "does-not-exist")
    p.detector = None
    assert len(p._frames) > 0                       # synthetic set generated
    assert all(f["path"] is None for f in p._frames)
    assert len(p.produce()) == 4


# ── Connected components + temporal delta ─────────────────────────────────────

def _analyse_synthetic(producer, ref: str, img, camera_id: str = "CAM-ALPHA"):
    producer._synthetic[ref] = img
    return producer._analyse(camera_id, {"frame_ref": ref, "path": None})


def test_two_separated_lines_counted_as_two_contrails(producer):
    img = sky_frame([(50, 50, 590, 60), (50, 170, 590, 180)])
    e = _analyse_synthetic(producer, "test_two_lines", img)
    assert e["contrail_detected"] is True
    assert e["contrail_count"] == 2
    assert e["contrail_pixel_ratio"] > 0
    assert e["mask_png_b64"]                     # mask attached
    EdgeVisionAI(**e)


def test_clear_sky_detects_nothing(producer):
    img = sky_frame([])                          # no bright lines
    e = _analyse_synthetic(producer, "test_clear", img)
    assert e["contrail_detected"] is False
    assert e["contrail_count"] == 0
    assert e["new_contrail_count"] == 0
    EdgeVisionAI(**e)


def test_temporal_delta_first_frame_all_components_are_new(producer):
    img = sky_frame([(50, 60, 590, 70)])
    e = _analyse_synthetic(producer, "test_delta_a", img, "CAM-EHBK")
    assert e["contrail_count"] >= 1
    assert e["new_contrail_count"] == e["contrail_count"]


def test_temporal_delta_repeated_component_is_not_new(producer):
    img = sky_frame([(50, 60, 590, 70)])
    _analyse_synthetic(producer, "test_delta_b1", img, "CAM-EHBK")
    e2 = _analyse_synthetic(producer, "test_delta_b2", img, "CAM-EHBK")
    assert e2["contrail_count"] >= 1
    assert e2["new_contrail_count"] == 0         # same contrail, zero new


def test_temporal_delta_added_line_counts_as_one_new(producer):
    base = sky_frame([(50, 60, 590, 70)])
    both = sky_frame([(50, 60, 590, 70), (50, 190, 590, 200)])
    _analyse_synthetic(producer, "test_delta_c1", base, "CAM-NORTH")
    e2 = _analyse_synthetic(producer, "test_delta_c2", both, "CAM-NORTH")
    assert e2["contrail_count"] == 2
    assert e2["new_contrail_count"] == 1


def test_temporal_delta_is_per_camera(producer):
    """Previous mask of one camera must not suppress 'new' on another camera."""
    img = sky_frame([(50, 60, 590, 70)])
    _analyse_synthetic(producer, "test_delta_d1", img, "CAM-ALPHA")
    e = _analyse_synthetic(producer, "test_delta_d2", img, "CAM-BRAVO")
    assert e["new_contrail_count"] == e["contrail_count"] >= 1


def test_mask_is_downscaled_to_256px(producer):
    import base64
    img = sky_frame([(50, 60, 590, 70)])
    e = _analyse_synthetic(producer, "test_mask_size", img)
    png = base64.b64decode(e["mask_png_b64"])
    mask = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
    assert max(mask.shape) <= 256


# ── Fallback without weights — must not require torch ─────────────────────────

def test_fallback_without_inference_module_or_weights(tmp_path, monkeypatch):
    """CI/demo case: no inference.py, no .pt weights — the built-in OpenCV
    heuristic must keep the channel alive without importing torch."""
    import emulator as em
    monkeypatch.setattr(em, "INFERENCE_DIR", str(tmp_path / "nowhere"))
    monkeypatch.delitem(sys.modules, "inference", raising=False)
    # Make sure the real edge-pi path can't be resolved either
    monkeypatch.setattr(sys, "path",
                        [p for p in sys.path if "edge-pi" not in p])

    torch_loaded_before = "torch" in sys.modules
    p = CameraProducer(frames_dir=tmp_path)
    assert p.detector is None                    # heuristic fallback engaged

    events = p.produce()
    assert len(events) == 4
    for e in events:
        EdgeVisionAI(**e)
    # The fallback path itself must not have pulled in torch
    if not torch_loaded_before:
        assert "torch" not in sys.modules


# ── EdgeVisionAI schema — negative cases (OWASP A03) ─────────────────────────

def _valid_vision(**overrides) -> dict:
    base = {
        "message_type": "EDGE_VISION_AI",
        "camera_id": "CAM-ALPHA",
        "timestamp": "2026-07-05T00:00:00+00:00",
        "contrail_detected": True,
        "confidence": 0.87,
        "contrail_pixel_ratio": 0.042,
        "contrail_count": 3,
        "new_contrail_count": 1,
        "frame_ref": "gvccs_val_00734",
        "mask_png_b64": "iVBORw0KGgo=",
    }
    base.update(overrides)
    return base


def test_vision_valid_message_accepted():
    EdgeVisionAI(**_valid_vision())


@pytest.mark.parametrize("field,value", [
    ("camera_id", "cam-alpha"),                  # lowercase — pattern violation
    ("camera_id", "CAM;DROP"),                   # injection characters
    ("camera_id", "C" * 21),                     # too long
    ("camera_id", "1CAM"),                       # must start with a letter
    ("confidence", 1.5),
    ("confidence", -0.1),
    ("contrail_pixel_ratio", 1.01),
    ("contrail_pixel_ratio", -0.001),
    ("contrail_count", -1),
    ("new_contrail_count", -1),
    ("contrail_count", 501),                     # above sanity cap
    ("frame_ref", "../../etc/passwd"),           # path traversal chars
    ("frame_ref", "Gvccs_VAL"),                  # uppercase — pattern violation
    ("mask_png_b64", "A" * 120_001),             # over payload cap
])
def test_vision_invalid_field_rejected(field, value):
    with pytest.raises(ValidationError):
        EdgeVisionAI(**_valid_vision(**{field: value}))


def test_vision_missing_camera_id_rejected():
    raw = _valid_vision()
    del raw["camera_id"]
    with pytest.raises(ValidationError):
        EdgeVisionAI(**raw)


def test_vision_mask_is_optional():
    EdgeVisionAI(**_valid_vision(mask_png_b64=None))


def test_camera_constants_match_java_camera_store():
    """Python copy of CameraStore.CAMERAS — keep in sync (CLAUDE.md Day 11)."""
    expected = [
        ("CAM-ALPHA", 50.60, 4.60), ("CAM-BRAVO", 51.90, 7.00),
        ("CAM-EHBK", 50.92, 5.77), ("CAM-NORTH", 52.30, 6.50),
    ]
    assert [(c["id"], c["lat"], c["lon"]) for c in CAMERAS] == expected
    assert all(c["elevation_cutoff_deg"] == 20.0 for c in CAMERAS)


# ── prepare_val_frames — split determinism / no leakage ──────────────────────

def test_val_indices_deterministic():
    assert val_indices(19_447) == val_indices(19_447)


def test_val_indices_reproduce_train_py_seed42_stream():
    """val_indices must replay EXACTLY random.seed(42)+shuffle from train.py."""
    random.seed(SEED)
    expected = list(range(1000))
    random.shuffle(expected)
    expected = expected[:int(1000 * VAL_FRACTION)]
    assert val_indices(1000) == expected


def test_val_indices_are_unique_and_in_range():
    idx = val_indices(1000)
    assert len(idx) == 100                       # 10 % val fraction
    assert len(set(idx)) == len(idx)
    assert all(0 <= i < 1000 for i in idx)


def test_manifest_frames_all_belong_to_val_split_no_leakage():
    """Every extracted frame must be a val-split member — train frames in the
    live channel would be data leakage (the old control_set mistake)."""
    manifest_path = HERE / "frames" / "manifest.json"
    if not manifest_path.exists():
        pytest.skip("frames/manifest.json not generated on this machine")
    manifest = json.loads(manifest_path.read_text())

    assert manifest["seed"] == SEED
    assert manifest["val_fraction"] == VAL_FRACTION
    val = val_indices(manifest["n_total"])
    val_set = set(val)

    refs = [f["frame_ref"] for f in manifest["frames"]]
    assert len(set(refs)) == len(refs)           # unique frame_refs
    for f in manifest["frames"]:
        assert f["dataset_index"] in val_set, \
            f"{f['frame_ref']} (idx {f['dataset_index']}) is NOT in the val split"
        pos = int(f["frame_ref"].rsplit("_", 1)[1])
        assert val[pos] == f["dataset_index"]    # frame_ref position consistent
