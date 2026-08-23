from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy
import pytest

from personal_ai_os.voice.adapters import (
    MicroWakeWordDetector,
    OpenWakeWordDetector,
    VoiceDependencyUnavailable,
    installed_version,
)
from personal_ai_os.voice.contracts import AudioFrame


def test_optional_voice_inventory_is_scalar_and_non_secret() -> None:
    assert installed_version("package-that-does-not-exist-for-bmo") is None


def test_custom_wake_model_uses_local_path_and_stem(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    selected: list[list[str]] = []

    class FakeModel:
        def __init__(self, *, wakeword_models: list[str], inference_framework: str) -> None:
            selected.append(wakeword_models)
            assert inference_framework == "onnx"

        def predict(self, _samples: object) -> dict[str, float]:
            return {"jarvis-custom": 0.9}

    monkeypatch.setattr(
        "personal_ai_os.voice.adapters.importlib.import_module",
        lambda name: (
            SimpleNamespace(Model=FakeModel)
            if name == "openwakeword.model"
            else numpy
            if name == "numpy"
            else None
        ),
    )
    model = tmp_path / "jarvis-custom.onnx"
    model.write_bytes(b"synthetic-model")
    detector = OpenWakeWordDetector(model_path=model, threshold=0.5)
    assert detector.model_name == "jarvis-custom"
    assert selected == [[str(model)]]
    assert detector.detected(AudioFrame(b"\x00\x00" * 1280)) is True


def test_custom_wake_model_rejects_missing_path(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="wake-word model is missing"):
        OpenWakeWordDetector(model_path=tmp_path / "missing.onnx")


def test_micro_wake_model_uses_exact_manifest_and_streaming_reset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    model = tmp_path / "jarvis-micro.tflite"
    manifest = tmp_path / "jarvis-micro.json"
    model.write_bytes(b"synthetic-model")
    manifest.write_text(json.dumps({"wake_word": "Jarvis", "model": model.name}), encoding="utf-8")

    class FakeFeatures:
        def process_streaming(self, _audio: bytes) -> list[object]:
            return [object()]

        def reset(self) -> None:
            return None

    class FakeWakeWord:
        probability_cutoff = 0.0

        @classmethod
        def from_config(cls, _path: Path) -> FakeWakeWord:
            return cls()

        def process_streaming(self, _feature: object) -> bool:
            return True

        def reset(self) -> None:
            return None

    monkeypatch.setattr(
        "personal_ai_os.voice.adapters.importlib.import_module",
        lambda name: (
            SimpleNamespace(MicroWakeWord=FakeWakeWord, MicroWakeWordFeatures=FakeFeatures)
            if name == "pymicro_wakeword"
            else None
        ),
    )
    detector = MicroWakeWordDetector(model_path=model, config_path=manifest, threshold=0.8)
    assert detector.model_name == "jarvis-micro"
    assert detector.detected(AudioFrame(b"\x00\x00" * 160)) is True
    detector.reset()


def test_micro_wake_model_rejects_wrong_phrase(tmp_path: Path) -> None:
    model = tmp_path / "not-jarvis.tflite"
    manifest = tmp_path / "not-jarvis.json"
    model.write_bytes(b"synthetic-model")
    manifest.write_text(
        json.dumps({"wake_word": "Hey Jarvis", "model": model.name}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="exact Jarvis phrase"):
        MicroWakeWordDetector(model_path=model, config_path=manifest)


def test_micro_wake_model_rejects_malformed_manifest_root(tmp_path: Path) -> None:
    model = tmp_path / "jarvis-micro.tflite"
    manifest = tmp_path / "jarvis-micro.json"
    model.write_bytes(b"synthetic-model")
    manifest.write_text("[]", encoding="utf-8")
    with pytest.raises(VoiceDependencyUnavailable, match="manifest is invalid"):
        MicroWakeWordDetector(model_path=model, config_path=manifest)
