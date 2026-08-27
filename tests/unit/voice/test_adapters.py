from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy
import pytest

from personal_ai_os.voice.adapters import (
    FasterWhisperWakePhraseRecognizer,
    OpenWakeWordDetector,
    VoiceDependencyUnavailable,
    installed_version,
    resolve_cuda_runtime_paths,
)
from personal_ai_os.voice.contracts import AudioFrame


def test_optional_voice_inventory_is_scalar_and_non_secret() -> None:
    assert installed_version("package-that-does-not-exist-for-bmo") is None


def test_cuda_runtime_resolution_requires_complete_dll_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("BMO_CUDA_RUNTIME_AUX_PATH", raising=False)
    monkeypatch.delenv("CUDA_PATH", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    original_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        "personal_ai_os.voice.adapters.importlib.util.find_spec",
        lambda name: None if name == "ctranslate2" else original_find_spec(name),
    )
    (tmp_path / "cudart64_12.dll").write_bytes(b"runtime")
    (tmp_path / "cublas64_12.dll").write_bytes(b"blas")
    with pytest.raises(RuntimeError, match=r"missing cudnn64_9\.dll"):
        resolve_cuda_runtime_paths(tmp_path)
    (tmp_path / "cudnn64_9.dll").write_bytes(b"cudnn")
    assert resolve_cuda_runtime_paths(tmp_path) == (tmp_path,)


def test_wake_verifier_uses_english_bounded_decode_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class FakeModel:
        def __init__(self, _model: str, *, device: str, compute_type: str) -> None:
            assert device == "cpu"
            assert compute_type == "int8"

        def transcribe(self, _audio: object, **kwargs: object):
            calls.append(kwargs)
            return ([SimpleNamespace(text="Jarvis")], SimpleNamespace())

    monkeypatch.setattr(
        "personal_ai_os.voice.adapters.importlib.import_module",
        lambda name: SimpleNamespace(WhisperModel=FakeModel) if name == "faster_whisper" else numpy,
    )
    recognizer = FasterWhisperWakePhraseRecognizer(
        model="local-small.en",
        beam_size=5,
        hotwords="Jarvis",
    )
    assert recognizer.transcribe((AudioFrame(b"\x01\x00" * 320),)) == "Jarvis"
    assert calls == [
        {
            "language": "en",
            "task": "transcribe",
            "condition_on_previous_text": False,
            "without_timestamps": True,
            "temperature": 0.0,
            "beam_size": 5,
            "hotwords": "Jarvis",
            "vad_filter": False,
            "word_timestamps": False,
        }
    ]


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


def test_official_wake_model_rejects_checksum_mismatch(tmp_path: Path) -> None:
    model = tmp_path / "hey_jarvis_v0.1.onnx"
    model.write_bytes(b"synthetic-model")

    with pytest.raises(VoiceDependencyUnavailable, match="checksum mismatch"):
        OpenWakeWordDetector(model_path=model, expected_sha256="0" * 64)


def test_openwakeword_temporal_policy_requires_hits_in_bounded_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scores = iter((0.8, 0.9, 0.1))

    class FakeModel:
        def __init__(self, **_kwargs: object) -> None:
            return None

        def predict(self, _samples: object) -> dict[str, float]:
            return {"hey_jarvis_v0.1": next(scores)}

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
    model = tmp_path / "hey_jarvis_v0.1.onnx"
    model.write_bytes(b"synthetic-model")
    detector = OpenWakeWordDetector(
        model_path=model,
        threshold=0.5,
        required_hits_in_window=2,
        temporal_window_frames=3,
    )
    frame = AudioFrame(b"\x00\x00" * 1280)
    assert detector.detected(frame) is False
    assert detector.detected(frame) is True
    assert detector.detected(frame) is True
    detector.reset()
    assert detector.last_score == 0.0


def test_openwakeword_passes_vad_threshold_to_upstream_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    model_kwargs: dict[str, object] = {}

    class FakeModel:
        def __init__(self, **kwargs: object) -> None:
            model_kwargs.update(kwargs)

        def predict(self, _samples: object) -> dict[str, float]:
            return {"hey_jarvis_v0.1": 0.4}

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
    model = tmp_path / "hey_jarvis_v0.1.onnx"
    model.write_bytes(b"synthetic-model")
    detector = OpenWakeWordDetector(
        model_path=model,
        threshold=0.2,
        temporal_policy="moving_max",
        deactivation_threshold=0.05,
        vad_threshold=0.35,
    )
    assert detector.detected(AudioFrame(b"\x00\x00" * 1280)) is True
    assert model_kwargs["vad_threshold"] == 0.35
