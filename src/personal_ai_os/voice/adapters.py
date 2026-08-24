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


class VoskWakeWordDetector:
    """Offline exact-bare-``Jarvis`` detector using a bounded Vosk grammar."""

    def __init__(
        self,
        *,
        model_path: Path,
        sample_rate_hz: int = 16_000,
        grammar: tuple[str, ...] = ("jarvis", "[unk]"),
    ) -> None:
        if not model_path.is_dir():
            raise VoiceDependencyUnavailable("configured Vosk model directory is missing")
        if sample_rate_hz != 16_000:
            raise ValueError("Vosk wake-word detection requires 16 kHz audio")
        if "jarvis" not in {item.casefold() for item in grammar}:
            raise ValueError("Vosk grammar must include the exact Jarvis phrase")
        try:
            module = importlib.import_module("vosk")
        except ImportError as exc:
            raise VoiceDependencyUnavailable("vosk is not installed") from exc
        try:
            if hasattr(module, "SetLogLevel"):
                module.SetLogLevel(-1)
            self._module = module
            self.model_path = model_path
            self.sample_rate_hz = sample_rate_hz
            self.grammar = tuple(grammar)
            self._model = module.Model(str(model_path))
            self._recognizer: Any
            self.reset()
        except (OSError, RuntimeError, ValueError) as exc:
            raise VoiceDependencyUnavailable("configured Vosk model could not be loaded") from exc

    @property
    def available(self) -> bool:
        return True

    def _new_recognizer(self) -> Any:
        recognizer = self._module.KaldiRecognizer(self._model, self.sample_rate_hz)
        recognizer.SetGrammar(json.dumps(list(self.grammar), ensure_ascii=False))
        return recognizer

    def detected(self, frame: AudioFrame) -> bool:
        if frame.sample_rate_hz != self.sample_rate_hz or frame.channels != 1:
            raise ValueError("Vosk wake frame format is unsupported")
        if not self._recognizer.AcceptWaveform(frame.pcm_s16le):
            return False
        try:
            result = json.loads(self._recognizer.Result())
        except (TypeError, json.JSONDecodeError):
            return False
        text = result.get("text") if isinstance(result, dict) else None
        return self._is_exact_jarvis(text)

    def reset(self) -> None:
        """Reset streaming recognizer state without retaining prior speech."""

        self._recognizer = self._new_recognizer()

    @staticmethod
    def _is_exact_jarvis(text: object) -> bool:
        if not isinstance(text, str):
            return False
        words = " ".join(text.casefold().split())
        return words == "jarvis"


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

    @staticmethod
    def _tensor_shape(model: Any, tensor: Any) -> list[int] | None:
        """Read only TFLite tensor dimensions for sanitized diagnostics."""

        try:
            dimensions = int(model.lib.TfLiteTensorNumDims(tensor))
            return [int(model.lib.TfLiteTensorDim(tensor, index)) for index in range(dimensions)]
        except (AttributeError, TypeError, ValueError):
            return None

    @staticmethod
    def _array_stats(values: Any) -> dict[str, float | None]:
        """Return scalar array statistics without retaining the array."""

        if getattr(values, "size", 0) == 0:
            return {"min": None, "max": None, "mean": None, "std": None}
        return {
            "min": round(float(values.min()), 6),
            "max": round(float(values.max()), 6),
            "mean": round(float(values.mean()), 6),
            "std": round(float(values.std()), 6),
        }

    def score_diagnostics(self, frame: AudioFrame) -> dict[str, Any]:
        """Inspect the real streaming scorer using scalar, non-audio diagnostics.

        This mirrors the pinned ``pymicro-wakeword`` quantization boundary only
        to report what is sent to TFLite.  It still delegates feature extraction,
        tensor copying, invocation, output copying, and dequantization to the
        runtime itself.  No PCM or feature arrays escape this method.
        """

        try:
            numpy = importlib.import_module("numpy")
        except ImportError as exc:
            raise VoiceDependencyUnavailable("numpy is required for scorer diagnostics") from exc

        model = self._model
        features = list(self._features.process_streaming(frame.pcm_s16le))
        feature_arrays: list[Any] = []
        quantized_inputs: list[Any] = []
        model_outputs: list[float] = []
        returned_scores: list[float] = []
        model_stride = int(getattr(model, "stride", 0))
        input_scale = float(getattr(model, "input_scale", 0.0))
        input_zero_point = int(getattr(model, "input_zero_point", 0))
        input_dtype = getattr(model, "input_dtype", None)

        for feature in features:
            feature_array = numpy.asarray(feature)
            feature_arrays.append(feature_array)
            pending = list(getattr(model, "_features", []))
            pending.append(feature_array)
            if model_stride > 0 and len(pending) >= model_stride and input_scale != 0.0:
                combined = numpy.concatenate(pending, axis=1)
                quantized_inputs.append(
                    numpy.round(combined / input_scale + input_zero_point).astype(input_dtype)
                )
            probability = model.process_streaming_prob(feature)
            if probability is not None:
                returned_scores.append(float(probability))
            probabilities = getattr(model, "_probabilities", ())
            if model_stride > 0 and len(pending) >= model_stride and probabilities:
                model_outputs.append(float(probabilities[-1]))

        def flattened_stats(values: list[Any]) -> dict[str, float | None]:
            if not values:
                return {"min": None, "max": None, "mean": None, "std": None}
            return self._array_stats(numpy.concatenate([value.reshape(-1) for value in values]))

        def changed(values: list[Any]) -> bool:
            if len(values) < 2:
                return False
            return any(not numpy.array_equal(values[0], value) for value in values[1:])

        def scalar_stats(values: list[float]) -> dict[str, float | None]:
            return self._array_stats(numpy.asarray(values, dtype=numpy.float32))

        output_dtype = getattr(model, "output_dtype", None)
        output_scale = float(getattr(model, "output_scale", 0.0))
        output_zero_point = int(getattr(model, "output_zero_point", 0))
        return {
            "feature_count": len(feature_arrays),
            "feature_shape": list(feature_arrays[0].shape) if feature_arrays else None,
            "feature_dtype": str(feature_arrays[0].dtype) if feature_arrays else None,
            "feature_stats": flattened_stats(feature_arrays),
            "feature_tensor_changed": changed(feature_arrays),
            "input_tensor_shape": self._tensor_shape(model, getattr(model, "input_tensor", None)),
            "input_tensor_dtype": str(input_dtype) if input_dtype is not None else None,
            "input_tensor_stats": flattened_stats(quantized_inputs),
            "input_tensor_changed": changed(quantized_inputs),
            "input_tensor_invocations": len(quantized_inputs),
            "input_quantization": {
                "scale": input_scale,
                "zero_point": input_zero_point,
            },
            "output_tensor_shape": self._tensor_shape(model, getattr(model, "output_tensor", None)),
            "output_tensor_dtype": str(output_dtype) if output_dtype is not None else None,
            "model_output_stats": scalar_stats(model_outputs),
            "model_output_changed": len(set(model_outputs)) > 1,
            "returned_score_stats": scalar_stats(returned_scores),
            "output_quantization": {
                "scale": output_scale,
                "zero_point": output_zero_point,
            },
        }

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
    "VoskWakeWordDetector",
    "installed_version",
]
