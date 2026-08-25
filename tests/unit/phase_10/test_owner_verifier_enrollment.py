from __future__ import annotations

import importlib.util
import sys
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
    )
    payload = __import__("json").loads(manifest.read_text(encoding="utf-8"))

    assert payload["production_ready"] is False
    assert payload["wake_contract"]["final_owner_verifier_accept_threshold"] == 0.67
    assert payload["wake_contract"]["openwakeword_vad_threshold"] is None
