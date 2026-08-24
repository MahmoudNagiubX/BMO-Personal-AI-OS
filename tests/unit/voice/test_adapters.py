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
    VoskWakeWordDetector,
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

        def process_streaming_prob(self, _feature: object) -> float:
            return 0.95

        def reset(self) -> None:
            return None

    monkeypatch.setattr(
        "personal_ai_os.voice.adapters.importlib.import_module",
        lambda name: (
            SimpleNamespace(MicroWakeWord=FakeWakeWord, MicroWakeWordFeatures=FakeFeatures)
            if name == "pymicro_wakeword"
            else numpy
            if name == "numpy"
            else None
        ),
    )
    detector = MicroWakeWordDetector(model_path=model, config_path=manifest, threshold=0.8)
    assert detector.model_name == "jarvis-micro"
    assert detector.detected(AudioFrame(b"\x00\x00" * 160)) is True
    assert detector.score(AudioFrame(b"\x00\x00" * 160)) == 0.95
    detector.reset()


def test_micro_wake_score_diagnostics_reports_changing_tensors_and_real_outputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    model = tmp_path / "jarvis-micro.tflite"
    manifest = tmp_path / "jarvis-micro.json"
    model.write_bytes(b"synthetic-model")
    manifest.write_text(json.dumps({"wake_word": "Jarvis", "model": model.name}), encoding="utf-8")

    class FakeFeatures:
        def process_streaming(self, _audio: bytes) -> list[numpy.ndarray]:
            return [
                numpy.asarray([[[1.0, 2.0]]]),
                numpy.asarray([[[3.0, 4.0]]]),
            ]

        def reset(self) -> None:
            return None

    class FakeLib:
        @staticmethod
        def TfLiteTensorNumDims(_tensor: object) -> int:
            return 3

        @staticmethod
        def TfLiteTensorDim(_tensor: object, index: int) -> int:
            return (1, 1, 2)[index]

    class FakeWakeWord:
        stride = 1
        input_scale = 1.0
        input_zero_point = 0
        input_dtype = numpy.int8
        output_scale = 0.5
        output_zero_point = 0
        output_dtype = numpy.uint8
        input_tensor = object()
        output_tensor = object()
        lib = FakeLib()

        def __init__(self) -> None:
            self._features: list[numpy.ndarray] = []
            self._probabilities: list[float] = []

        @classmethod
        def from_config(cls, _path: Path) -> FakeWakeWord:
            return cls()

        def process_streaming_prob(self, feature: numpy.ndarray) -> float:
            self._features.append(feature)
            self._probabilities.append(float(feature.mean()) * self.output_scale)
            self._features.clear()
            return self._probabilities[-1]

        def reset(self) -> None:
            self._features.clear()
            self._probabilities.clear()

    monkeypatch.setattr(
        "personal_ai_os.voice.adapters.importlib.import_module",
        lambda name: (
            SimpleNamespace(MicroWakeWord=FakeWakeWord, MicroWakeWordFeatures=FakeFeatures)
            if name == "pymicro_wakeword"
            else numpy
            if name == "numpy"
            else None
        ),
    )
    detector = MicroWakeWordDetector(model_path=model, config_path=manifest)
    diagnostics = detector.score_diagnostics(AudioFrame(b"\x00\x00" * 160))

    assert diagnostics["feature_tensor_changed"] is True
    assert diagnostics["input_tensor_changed"] is True
    assert diagnostics["input_tensor_shape"] == [1, 1, 2]
    assert diagnostics["input_tensor_dtype"] == "<class 'numpy.int8'>"
    assert diagnostics["model_output_changed"] is True
    assert diagnostics["model_output_stats"] == {
        "min": 0.75,
        "max": 1.75,
        "mean": 1.25,
        "std": 0.5,
    }


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


def test_vosk_detector_uses_exact_jarvis_grammar_and_rejects_extra_words(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    model_path = tmp_path / "vosk-model-small-en-us-0.15"
    model_path.mkdir()
    results = iter(
        [
            json.dumps({"text": "jarvis"}),
            json.dumps({"text": "hey jarvis"}),
        ]
    )
    grammars: list[str] = []

    class FakeRecognizer:
        def __init__(self, _model: object, sample_rate: int) -> None:
            assert sample_rate == 16_000

        def SetGrammar(self, grammar: str) -> None:
            grammars.append(grammar)

        def AcceptWaveform(self, _audio: bytes) -> bool:
            return True

        def Result(self) -> str:
            return next(results)

    fake_vosk = SimpleNamespace(
        Model=lambda path: object(),
        KaldiRecognizer=FakeRecognizer,
    )
    monkeypatch.setattr(
        "personal_ai_os.voice.adapters.importlib.import_module",
        lambda name: fake_vosk if name == "vosk" else None,
    )

    detector = VoskWakeWordDetector(model_path=model_path)
    frame = AudioFrame(b"\x00\x00" * 160)
    assert detector.detected(frame) is True
    assert detector.detected(frame) is False
    assert json.loads(grammars[0]) == ["jarvis", "[unk]"]


def test_vosk_detector_rejects_non_16khz_or_stereo_frames(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    model_path = tmp_path / "vosk-model"
    model_path.mkdir()

    class FakeRecognizer:
        def SetGrammar(self, _grammar: str) -> None:
            return None

    fake_vosk = SimpleNamespace(
        Model=lambda path: object(), KaldiRecognizer=lambda *_: FakeRecognizer()
    )
    monkeypatch.setattr(
        "personal_ai_os.voice.adapters.importlib.import_module",
        lambda name: fake_vosk if name == "vosk" else None,
    )
    detector = VoskWakeWordDetector(model_path=model_path)
    with pytest.raises(ValueError, match="unsupported"):
        detector.detected(AudioFrame(b"\x00\x00" * 160, sample_rate_hz=8_000))
