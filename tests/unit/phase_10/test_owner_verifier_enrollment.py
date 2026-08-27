from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest


def _module() -> object:
    root = Path(__file__).resolve().parents[3]
    path = root / "scripts/phase_10/enroll_hey_jarvis_owner.py"
    spec = importlib.util.spec_from_file_location("owner_enrollment", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_final_threshold_is_held_out_and_never_hard_coded() -> None:
    module = _module()
    threshold = module._select_final_accept_threshold([0.71, 0.73], [0.20, 0.31])

    assert threshold == pytest.approx(0.51)
    assert threshold != 0.5
    assert module._select_final_accept_threshold([0.31, 0.73], [0.20, 0.31]) is None


def test_negative_splits_are_non_overlapping() -> None:
    module = _module()
    source = np.arange(module.SAMPLE_RATE_HZ * 15, dtype=np.int16)

    train, holdout = module._split_samples(source, 10.0)

    assert len(train) == module.SAMPLE_RATE_HZ * 10
    assert len(holdout) == module.SAMPLE_RATE_HZ * 5
    assert train[-1] + 1 == holdout[0]


def test_audio_quality_gate_accepts_quiet_speech_above_ambient() -> None:
    module = _module()
    ambient = module.AudioLevels(rms=0.0002, peak=0.001)

    assert module._positive_audio_is_usable(module.AudioLevels(rms=0.0006, peak=0.004), ambient)
    assert not module._positive_audio_is_usable(module.AudioLevels(rms=0.0002, peak=0.001), ambient)


def test_only_bad_positive_capture_is_retried_once(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    calls: list[float] = []
    frames = [
        np.zeros(round(module.POSITIVE_CAPTURE_SECONDS * module.SAMPLE_RATE_HZ), dtype=np.int16),
        np.full(
            round(module.POSITIVE_CAPTURE_SECONDS * module.SAMPLE_RATE_HZ), 800, dtype=np.int16
        ),
    ]

    def capture(_sounddevice: object, *, seconds: float, device: str | None) -> np.ndarray:
        assert device is None
        calls.append(seconds)
        return frames.pop(0)

    monkeypatch.setattr(module, "_capture", capture)
    monkeypatch.setattr(module, "_countdown", lambda _label: None)

    _samples, levels = module._capture_positive(
        object(),
        condition="reserved validation",
        device=None,
        ambient=module.AudioLevels(rms=0.0002, peak=0.001),
    )

    assert len(calls) == 2
    assert levels.rms > 0.01


def test_manifest_keeps_profile_provisional_and_vad_disabled(tmp_path: Path) -> None:
    module = _module()
    model = tmp_path / "hey_jarvis_v0.1.onnx"
    model.write_bytes(b"test")

    manifest = module._write_manifest(
        tmp_path,
        base_model_path=model,
        artifact_sha256="a" * 64,
        validation={"raw_audio_retained": False},
        final_threshold=0.67,
        base_threshold=0.42,
        base_calibration={"candidate_recall": 0.998},
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    assert payload["production_ready"] is False
    assert payload["wake_contract"]["final_owner_verifier_accept_threshold"] == 0.67
    assert payload["wake_contract"]["openwakeword_vad_threshold"] is None


def test_bmo_extractor_uses_calibrated_threshold_not_upstream_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    from scripts.phase_10 import owner_verifier_training as training

    observed: dict[str, object] = {}

    def fake_extract(
        _clip: str, _model: object, _name: str, *, threshold: float, N: int
    ) -> np.ndarray:
        observed["threshold"] = threshold
        observed["variations"] = N
        return np.ones((2, 5, 96), dtype=np.float32)

    fake_upstream = types.ModuleType("openwakeword.custom_verifier_model")
    fake_upstream.get_reference_clip_features = fake_extract
    original_import = importlib.import_module

    def fake_import(name: str, package: str | None = None) -> object:
        if name == "openwakeword.custom_verifier_model":
            return fake_upstream
        return original_import(name, package)

    monkeypatch.setattr(training.importlib, "import_module", fake_import)

    features = training.extract_positive_features(
        "temporary.wav",
        object(),
        "hey_jarvis_v0.1",
        base_candidate_invoke_threshold=0.27,
    )

    assert features.shape == (2, 5, 96)
    assert observed == {"threshold": 0.27, "variations": 5}


def test_bmo_training_wrapper_passes_calibrated_threshold_to_upstream_helpers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import importlib

    from scripts.phase_10 import owner_verifier_training as training

    observed: dict[str, object] = {}
    thresholds: list[float] = []
    variations: list[int] = []

    def fake_extract(
        _clip: str, _model: object, _name: str, *, threshold: float, N: int
    ) -> np.ndarray:
        thresholds.append(threshold)
        observed["thresholds"] = thresholds
        variations.append(N)
        if threshold not in (0.0, 0.23):
            raise AssertionError("an unexpected threshold reached the upstream helper")
        return np.ones((2, 5, 96), dtype=np.float32)

    def fake_train(features: np.ndarray, labels: np.ndarray) -> dict[str, object]:
        observed["training_shape"] = features.shape
        observed["label_shape"] = labels.shape
        return {"model": "synthetic"}

    class FakeModel:
        def __init__(self, **_kwargs: object) -> None:
            pass

    custom_module = types.ModuleType("openwakeword.custom_verifier_model")
    custom_module.get_reference_clip_features = fake_extract
    custom_module.train_verifier_model = fake_train
    openwakeword_module = types.ModuleType("openwakeword")
    openwakeword_module.Model = FakeModel
    original_import = importlib.import_module

    def fake_import(name: str, package: str | None = None) -> object:
        if name == "openwakeword":
            return openwakeword_module
        if name == "openwakeword.custom_verifier_model":
            return custom_module
        return original_import(name, package)

    monkeypatch.setattr(training.importlib, "import_module", fake_import)
    model_path = tmp_path / "hey_jarvis_v0.1.onnx"
    model_path.write_bytes(b"model")
    output_path = tmp_path / "verifier.joblib"

    stats = training.train_calibrated_verifier(
        [tmp_path / "positive.wav"],
        [tmp_path / "negative.wav"],
        base_model_path=model_path,
        output_path=output_path,
        base_candidate_invoke_threshold=0.23,
    )

    assert output_path.is_file()
    assert stats["base_candidate_invoke_threshold"] == 0.23
    assert thresholds.count(0.23) == 1
    assert thresholds.count(0.0) == 1
    assert variations == [5, 1]
    assert observed["training_shape"] == (4, 5, 96)
    assert observed["label_shape"] == (4,)
