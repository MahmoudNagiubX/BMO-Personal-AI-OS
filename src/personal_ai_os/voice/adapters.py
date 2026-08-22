"""Optional local engine adapters; imports stay behind product-owned boundaries."""

from __future__ import annotations

import array
import importlib
import importlib.metadata
import importlib.util
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

    def __init__(self, *, model_name: str = "hey_jarvis", threshold: float = 0.5) -> None:
        try:
            module = importlib.import_module("openwakeword.model")
        except ImportError as exc:
            raise VoiceDependencyUnavailable("openwakeword is not installed") from exc
        self.model_name = model_name
        self.threshold = threshold
        self._model: Any = module.Model(wakeword_models=[model_name], inference_framework="onnx")

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
    "OpenWakeWordDetector",
    "SherpaOnnxPiperSynthesizer",
    "SileroVoiceActivityDetector",
    "VoiceDependencyUnavailable",
    "installed_version",
]
