from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy
import pytest

from personal_ai_os.voice.adapters import OpenWakeWordDetector, installed_version
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
