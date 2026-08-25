from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy
import pytest

from personal_ai_os.voice.adapters import (
    SHERPA_ONNX_KWS_ARCHIVE_SHA256,
    SHERPA_ONNX_KWS_ARTIFACT,
    FasterWhisperWakePhraseRecognizer,
    MicroWakeWordDetector,
    OpenWakeWordDetector,
    PocketSphinxWakeWordDetector,
    SherpaOnnxWakeWordDetector,
    VoiceDependencyUnavailable,
    VoskWakeWordDetector,
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


def test_sherpa_kws_verifies_manifest_and_accepts_only_exact_jarvis(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    model_path = tmp_path / "sherpa"
    model_path.mkdir()
    file_names = (
        "bpe.model",
        "tokens.txt",
        "encoder-epoch-12-avg-2-chunk-16-left-64.onnx",
        "decoder-epoch-12-avg-2-chunk-16-left-64.onnx",
        "joiner-epoch-12-avg-2-chunk-16-left-64.onnx",
        "README.md",
        "keywords.txt",
    )
    for name in file_names:
        (model_path / name).write_bytes(name.encode())
    (model_path / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "phase-10-sherpa-onnx-kws/v1",
                "artifact": SHERPA_ONNX_KWS_ARTIFACT,
                "archive_sha256": SHERPA_ONNX_KWS_ARCHIVE_SHA256,
                "wake_word": "Jarvis",
                "license": "Apache-2.0",
                "keyword_file": "keywords.txt",
                "keyword_line_count": 1,
                "files": {
                    name: hashlib.sha256((model_path / name).read_bytes()).hexdigest()
                    for name in file_names
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeSpotter:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs["keywords_file"] == str(model_path / "keywords.txt")
            self.results = iter(("Jarvis", "Hey Jarvis"))

        def create_stream(self) -> object:
            return SimpleNamespace(accept_waveform=lambda *_args: None)

        def is_ready(self, _stream: object) -> bool:
            return False

        def decode_stream(self, _stream: object) -> None:
            return None

        def get_result(self, _stream: object) -> str:
            return next(self.results)

        def reset_stream(self, _stream: object) -> None:
            return None

    class FakeModule:
        KeywordSpotter = FakeSpotter

    monkeypatch.setattr(
        "personal_ai_os.voice.adapters.importlib.import_module",
        lambda name: FakeModule() if name == "sherpa_onnx" else __import__(name),
    )
    detector = SherpaOnnxWakeWordDetector(
        model_path=model_path,
        manifest_path=model_path / "manifest.json",
    )
    frame = AudioFrame(b"\x00\x00" * 160)
    assert detector.detected(frame) is True
    assert detector.detected(frame) is False


def test_sherpa_kws_rejects_tampered_runtime_file(tmp_path: Path) -> None:
    model_path = tmp_path / "sherpa"
    model_path.mkdir()
    manifest = model_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "phase-10-sherpa-onnx-kws/v1",
                "artifact": SHERPA_ONNX_KWS_ARTIFACT,
                "archive_sha256": SHERPA_ONNX_KWS_ARCHIVE_SHA256,
                "wake_word": "Jarvis",
                "license": "Apache-2.0",
                "keyword_file": "keywords.txt",
                "keyword_line_count": 1,
                "files": {"keywords.txt": "0" * 64},
            }
        ),
        encoding="utf-8",
    )
    (model_path / "keywords.txt").write_text("jarvis\n", encoding="utf-8")
    with pytest.raises(VoiceDependencyUnavailable, match="verification failed"):
        SherpaOnnxWakeWordDetector(model_path=model_path, manifest_path=manifest)


def test_pocketsphinx_adapter_is_exact_and_resettable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeConfig:
        def set_float(self, name: str, value: float) -> None:
            assert name == "-kws_threshold"
            assert value > 0

    class FakeDecoder:
        def __init__(self, _config: FakeConfig) -> None:
            self.hypotheses = iter(("jarvis", "hey jarvis"))

        def add_keyphrase(self, name: str, phrase: str) -> None:
            assert (name, phrase) == ("jarvis", "jarvis")

        def activate_search(self, name: str) -> None:
            assert name == "jarvis"

        def start_utt(self) -> None:
            return None

        def end_utt(self) -> None:
            return None

        def process_raw(self, _data: bytes, _no_search: bool, _full_utt: bool) -> None:
            return None

        def hyp(self) -> object:
            return SimpleNamespace(hypstr=next(self.hypotheses))

    fake = SimpleNamespace(Config=FakeConfig, Decoder=FakeDecoder)
    monkeypatch.setattr(
        "personal_ai_os.voice.adapters.importlib.import_module",
        lambda name: fake if name == "pocketsphinx" else None,
    )
    detector = PocketSphinxWakeWordDetector()
    frame = AudioFrame(b"\x00\x00" * 160)
    assert detector.detected(frame) is True
    assert detector.detected(frame) is False
