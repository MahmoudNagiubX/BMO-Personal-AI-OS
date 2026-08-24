"""Optional local engine adapters; imports stay behind product-owned boundaries."""

from __future__ import annotations

import array
import importlib
import importlib.metadata
import importlib.util
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from personal_ai_os.voice.contracts import AudioFrame

_DLL_HANDLES: list[object] = []


def _prepare_windows_native_libraries() -> None:
    """Prefer wheel-bundled ONNX DLLs over a stale system32 copy on Windows."""

    if sys.platform != "win32":
        return
    directories: list[Path] = []
    for package, child in (("onnxruntime", "capi"), ("sherpa_onnx", "lib")):
        spec = importlib.util.find_spec(package)
        if spec is not None and spec.origin:
            directory = Path(spec.origin).parent / child
            if directory.is_dir():
                directories.append(directory)
    for directory in directories:
        _DLL_HANDLES.append(os.add_dll_directory(str(directory)))
        os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")


class VoiceDependencyUnavailable(RuntimeError):
    """Raised when an explicitly selected local voice dependency is unavailable."""


def installed_version(distribution: str) -> str | None:
    """Return a package version without importing its runtime or loading a model."""

    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


class OpenWakeWordDetector:
    """openWakeWord adapter used only for bounded local wake detection."""

    def __init__(
        self,
        *,
        model_name: str = "hey_jarvis",
        model_path: Path | None = None,
        threshold: float = 0.5,
    ) -> None:
        if model_path is not None:
            if model_path.suffix.casefold() not in {".onnx", ".tflite"}:
                raise ValueError("wake-word model must be an ONNX or TFLite artifact")
            if not model_path.is_file():
                raise VoiceDependencyUnavailable("configured wake-word model is missing")
        try:
            module = importlib.import_module("openwakeword.model")
        except ImportError as exc:
            raise VoiceDependencyUnavailable("openwakeword is not installed") from exc
        if model_path is not None:
            selected_model = str(model_path)
            self.model_name = model_path.stem
        else:
            selected_model = model_name
            self.model_name = model_name
        self.threshold = threshold
        self._model: Any = module.Model(
            wakeword_models=[selected_model], inference_framework="onnx"
        )

    @property
    def available(self) -> bool:
        return True

    def detected(self, frame: AudioFrame) -> bool:
        try:
            numpy = importlib.import_module("numpy")
        except ImportError as exc:
            raise VoiceDependencyUnavailable("numpy is required by openwakeword") from exc
        scores = self._model.predict(numpy.frombuffer(frame.pcm_s16le, dtype=numpy.int16))
        value = scores.get(self.model_name, 0.0)
        return isinstance(value, (int, float)) and value >= self.threshold


class MicroWakeWordDetector:
    """Product-owned adapter for local microWakeWord streaming models."""

    def __init__(
        self,
        *,
        model_path: Path,
        config_path: Path | None = None,
        threshold: float | None = None,
    ) -> None:
        if model_path.suffix.casefold() != ".tflite":
            raise ValueError("microWakeWord model must be a TFLite artifact")
        if not model_path.is_file():
            raise VoiceDependencyUnavailable("configured microWakeWord model is missing")
        selected_config = config_path or model_path.with_suffix(".json")
        if not selected_config.is_file():
            raise VoiceDependencyUnavailable("configured microWakeWord manifest is missing")
        try:
            config = json.loads(selected_config.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise VoiceDependencyUnavailable(
                "configured microWakeWord manifest is invalid"
            ) from exc
        if not isinstance(config, dict):
            raise VoiceDependencyUnavailable("configured microWakeWord manifest is invalid")
        if config.get("wake_word") != "Jarvis":
            raise ValueError("microWakeWord manifest must target the exact Jarvis phrase")
        if Path(str(config.get("model", ""))).name != model_path.name:
            raise ValueError("microWakeWord manifest model does not match the artifact")
        try:
            module = importlib.import_module("pymicro_wakeword")
        except ImportError as exc:
            raise VoiceDependencyUnavailable("pymicro-wakeword is not installed") from exc
        try:
            self._model: Any = module.MicroWakeWord.from_config(selected_config)
            self._features: Any = module.MicroWakeWordFeatures()
        except (OSError, RuntimeError, ValueError) as exc:
            raise VoiceDependencyUnavailable(
                "configured microWakeWord model could not be loaded"
            ) from exc
        if threshold is not None:
            if not 0.0 <= threshold <= 1.0:
                raise ValueError("wake-word threshold must be between 0 and 1")
            self._model.probability_cutoff = threshold
        self.model_name = model_path.stem

    @property
    def available(self) -> bool:
        return True

    def detected(self, frame: AudioFrame) -> bool:
        for feature in self._features.process_streaming(frame.pcm_s16le):
            if self._model.process_streaming(feature) is True:
                return True
        return False

    def score(self, frame: AudioFrame) -> float:
        """Return the highest scalar probability for calibration only."""

        maximum = 0.0
        for feature in self._features.process_streaming(frame.pcm_s16le):
            probability = self._model.process_streaming_prob(feature)
            if probability is None:
                continue
            value = float(probability)
            if value == value:
                maximum = max(maximum, min(1.0, max(0.0, value)))
        return maximum

    def reset(self) -> None:
        """Reset streaming feature and model state between bounded probes."""

        self._features.reset()
        self._model.reset()


class SileroVoiceActivityDetector:
    """Silero VAD adapter loaded lazily after wake/manual activation."""

    def __init__(self, *, threshold: float = 0.5) -> None:
        try:
            self._module = importlib.import_module("silero_vad")
        except ImportError as exc:
            raise VoiceDependencyUnavailable("silero-vad is not installed") from exc
        self.threshold = threshold
        self._model: Any | None = None

    def _load(self) -> Any:
        if self._model is None:
            loader = getattr(self._module, "load_silero_vad", None)
            if not callable(loader):
                raise VoiceDependencyUnavailable("silero-vad loader is unavailable")
            self._model = loader()
        return self._model

    def contains_speech(self, frames: Sequence[AudioFrame]) -> bool:
        try:
            torch = importlib.import_module("torch")
        except ImportError as exc:
            raise VoiceDependencyUnavailable("torch is required by silero-vad") from exc
        get_timestamps = getattr(self._module, "get_speech_timestamps", None)
        if not callable(get_timestamps):
            raise VoiceDependencyUnavailable("silero-vad timestamp API is unavailable")
        pcm = b"".join(frame.pcm_s16le for frame in frames)
        samples = array.array("h", pcm)
        audio = torch.tensor(samples, dtype=torch.float32) / 32768.0
        return bool(get_timestamps(audio, self._load(), sampling_rate=16_000))


class FasterWhisperRecognizer:
    """Lazy multilingual faster-whisper medium adapter with no temporary audio file."""

    def __init__(
        self,
        *,
        model: str = "medium",
        device: str = "cuda",
        compute_type: str = "float16",
        cuda_runtime_path: str | None = None,
    ) -> None:
        if cuda_runtime_path is not None:
            if not Path(cuda_runtime_path).is_dir():
                raise VoiceDependencyUnavailable("configured CUDA runtime directory is missing")
            if sys.platform == "win32":
                _DLL_HANDLES.append(os.add_dll_directory(cuda_runtime_path))
                os.environ["PATH"] = cuda_runtime_path + os.pathsep + os.environ.get("PATH", "")
        try:
            module = importlib.import_module("faster_whisper")
        except ImportError as exc:
            raise VoiceDependencyUnavailable("faster-whisper is not installed") from exc
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self._model: Any = module.WhisperModel(model, device=device, compute_type=compute_type)

    def transcribe(self, frames: Sequence[AudioFrame]) -> str:
        try:
            numpy = importlib.import_module("numpy")
        except ImportError as exc:
            raise VoiceDependencyUnavailable("numpy is required by faster-whisper") from exc
        pcm = b"".join(frame.pcm_s16le for frame in frames)
        audio = numpy.frombuffer(pcm, dtype=numpy.int16).astype(numpy.float32) / 32768.0
        segments, _ = self._model.transcribe(audio, vad_filter=False)
        return " ".join(str(segment.text).strip() for segment in segments).strip()


class SherpaOnnxPiperSynthesizer:
    """sherpa-onnx VITS/Piper adapter configured by external model files."""

    def __init__(self, *, model: str, tokens: str, data_dir: str = "") -> None:
        _prepare_windows_native_libraries()
        try:
            module = importlib.import_module("sherpa_onnx")
        except ImportError as exc:
            raise VoiceDependencyUnavailable("sherpa-onnx is not installed") from exc
        self.model = model
        self.tokens = tokens
        vits = module.OfflineTtsVitsModelConfig()
        vits.model = model
        vits.tokens = tokens
        vits.data_dir = data_dir
        model_config = module.OfflineTtsModelConfig()
        model_config.vits = vits
        tts_config = module.OfflineTtsConfig()
        tts_config.model = model_config
        self._tts: Any = module.OfflineTts(tts_config)

    def synthesize(self, text: str) -> Sequence[AudioFrame]:
        audio = self._tts.generate(text)
        samples = getattr(audio, "samples", None)
        sample_rate = int(getattr(audio, "sample_rate", 22_050))
        if samples is None:
            raise VoiceDependencyUnavailable("sherpa-onnx returned no audio")
        pcm = array.array(
            "h",
            (int(max(-1.0, min(1.0, float(value))) * 32767) for value in samples),
        )
        return (AudioFrame(pcm_s16le=pcm.tobytes(), sample_rate_hz=sample_rate),)


__all__ = [
    "FasterWhisperRecognizer",
    "MicroWakeWordDetector",
    "OpenWakeWordDetector",
    "SherpaOnnxPiperSynthesizer",
    "SileroVoiceActivityDetector",
    "VoiceDependencyUnavailable",
    "installed_version",
]
