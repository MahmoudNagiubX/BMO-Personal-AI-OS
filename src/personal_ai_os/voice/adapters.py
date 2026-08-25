"""Optional local engine adapters; imports stay behind product-owned boundaries."""

from __future__ import annotations

import array
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
import sys
from collections import deque
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from personal_ai_os.voice.contracts import AudioFrame
from personal_ai_os.voice.mfcc import (
    extract_mfcc,
    normalized_subsequence_dtw_distance_from,
    read_mfcc_profile,
)
from personal_ai_os.voice.wake_phrase import PRIMARY_WAKE_PHRASE

_DLL_HANDLES: list[object] = []

CUDA_RUNTIME_DLLS = ("cudart64_12.dll", "cublas64_12.dll", "cudnn64_9.dll")


def _runtime_inputs(value: str | Path | Sequence[str | Path] | None) -> list[Path]:
    if value is None:
        return []
    if isinstance(value, (str, Path)):
        return [Path(value)]
    return [Path(item) for item in value]


def _find_dll(directory: Path, name: str) -> Path | None:
    direct = directory / name
    if direct.is_file():
        return direct
    try:
        return next(
            item
            for item in directory.iterdir()
            if item.is_file() and item.name.casefold() == name.casefold()
        )
    except (OSError, StopIteration):
        return None


def resolve_cuda_runtime_paths(
    explicit: str | Path | Sequence[str | Path] | None = None,
) -> tuple[Path, ...]:
    """Resolve and verify the complete local CTranslate2 CUDA DLL set.

    CUDA runtime components may be supplied by the accepted local llama.cpp
    bundle while cuDNN is supplied by the pinned CTranslate2 wheel. Every
    required DLL must be found before any native library is loaded.
    """

    roots = _runtime_inputs(explicit)
    auxiliary = os.environ.get("BMO_CUDA_RUNTIME_AUX_PATH", "")
    roots.extend(Path(item) for item in auxiliary.split(os.pathsep) if item)
    cuda_path = os.environ.get("CUDA_PATH")
    if cuda_path:
        roots.append(Path(cuda_path) / "bin")
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        roots.extend(
            item.parent
            for item in Path(local_app_data, "BMO").glob("llama.cpp/**/cudart64_12.dll")
            if item.is_file()
        )
    ctranslate2_spec = importlib.util.find_spec("ctranslate2")
    if ctranslate2_spec is not None and ctranslate2_spec.origin:
        roots.append(Path(ctranslate2_spec.origin).parent)

    unique_roots: list[Path] = []
    for root in roots:
        resolved = root.expanduser()
        if resolved.is_dir() and resolved not in unique_roots:
            unique_roots.append(resolved)
    selected: dict[str, Path] = {}
    for name in CUDA_RUNTIME_DLLS:
        for root in unique_roots:
            found = _find_dll(root, name)
            if found is not None:
                selected[name] = found.parent
                break
    missing = [name for name in CUDA_RUNTIME_DLLS if name not in selected]
    if missing:
        raise VoiceDependencyUnavailable(
            "complete CTranslate2 CUDA runtime is unavailable; missing " + ", ".join(missing)
        )
    return tuple(dict.fromkeys(selected.values()))


def _register_dll_directory(directory: Path) -> None:
    """Register a native DLL search directory on Windows; no-op on other platforms."""

    if sys.platform != "win32":
        return
    add_dll_directory = getattr(os, "add_dll_directory", None)
    if callable(add_dll_directory):
        _DLL_HANDLES.append(add_dll_directory(str(directory)))
    os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")


def _load_cuda_runtime(
    explicit: str | Path | Sequence[str | Path] | None,
) -> tuple[Path, ...]:
    paths = resolve_cuda_runtime_paths(explicit)
    for directory in paths:
        _register_dll_directory(directory)
    return paths


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
        _register_dll_directory(directory)


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
        model_name: str = "hey_jarvis_v0.1",
        model_path: Path | None = None,
        threshold: float = 0.5,
        expected_sha256: str | None = None,
        required_hits_in_window: int = 1,
        temporal_window_frames: int = 3,
    ) -> None:
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("wake-word threshold must be between 0 and 1")
        if not 1 <= required_hits_in_window <= temporal_window_frames:
            raise ValueError("wake-word temporal hit bounds are invalid")
        if model_path is not None:
            if model_path.suffix.casefold() not in {".onnx", ".tflite"}:
                raise ValueError("wake-word model must be an ONNX or TFLite artifact")
            if not model_path.is_file():
                raise VoiceDependencyUnavailable("configured wake-word model is missing")
            if expected_sha256 is not None:
                actual_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()
                if actual_sha256.casefold() != expected_sha256.casefold():
                    raise VoiceDependencyUnavailable("configured wake-word model checksum mismatch")
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
        self.required_hits_in_window = required_hits_in_window
        self.temporal_window_frames = temporal_window_frames
        self._hit_window: deque[bool] = deque(maxlen=temporal_window_frames)
        self.expected_phrase = PRIMARY_WAKE_PHRASE
        self.last_score = 0.0
        self._model: Any = module.Model(
            wakeword_models=[selected_model], inference_framework="onnx"
        )

    @property
    def available(self) -> bool:
        return True

    def detected(self, frame: AudioFrame) -> bool:
        hit = self.score(frame) >= self.threshold
        self._hit_window.append(hit)
        return sum(self._hit_window) >= self.required_hits_in_window

    def score(self, frame: AudioFrame) -> float:
        """Return the current scalar model score without retaining PCM."""

        try:
            numpy = importlib.import_module("numpy")
        except ImportError as exc:
            raise VoiceDependencyUnavailable("numpy is required by openwakeword") from exc
        scores = self._model.predict(numpy.frombuffer(frame.pcm_s16le, dtype=numpy.int16))
        value = scores.get(self.model_name, 0.0)
        try:
            self.last_score = float(value)
        except (TypeError, ValueError):
            self.last_score = 0.0
        return self.last_score

    def reset(self) -> None:
        """Reset the model's streaming feature state between speech candidates."""

        reset = getattr(self._model, "reset", None)
        if callable(reset):
            reset()
        self.last_score = 0.0
        self._hit_window.clear()


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


SHERPA_ONNX_KWS_ARTIFACT = "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"
SHERPA_ONNX_KWS_ARCHIVE_SHA256 = "f170013b4716e41b62b9bfd809687c207cef798ef9bc6534d524e17af9b6561a"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SherpaOnnxWakeWordDetector:
    """Product-owned exact-``Jarvis`` adapter for official sherpa-onnx KWS.

    The external model directory is accepted only with a generated manifest
    that pins the official archive, every runtime file, and the one-line
    keyword file. The third-party stream remains behind this adapter and PCM
    is converted to a bounded in-memory float frame only for inference.
    """

    def __init__(
        self,
        *,
        model_path: Path,
        manifest_path: Path,
        keywords_path: Path | None = None,
        sample_rate_hz: int = 16_000,
        num_threads: int = 1,
        threshold: float = 0.25,
    ) -> None:
        if not model_path.is_dir():
            raise VoiceDependencyUnavailable(
                "configured sherpa-onnx KWS model directory is missing"
            )
        if sample_rate_hz != 16_000:
            raise ValueError("sherpa-onnx KWS requires 16 kHz audio")
        if num_threads < 1:
            raise ValueError("sherpa-onnx KWS requires at least one CPU thread")
        if not 0.0 < threshold <= 1.0:
            raise ValueError("sherpa-onnx KWS threshold must be between 0 and 1")
        manifest = self._load_manifest(model_path, manifest_path)
        selected_keywords = model_path / str(manifest["keyword_file"])
        if keywords_path is not None and keywords_path.resolve() != selected_keywords.resolve():
            raise ValueError("configured sherpa-onnx keyword file does not match its manifest")
        if not selected_keywords.is_file():
            raise VoiceDependencyUnavailable("configured sherpa-onnx keyword file is missing")
        try:
            module = importlib.import_module("sherpa_onnx")
            self._spotter: Any = module.KeywordSpotter(
                tokens=str(model_path / "tokens.txt"),
                encoder=str(model_path / "encoder-epoch-12-avg-2-chunk-16-left-64.onnx"),
                decoder=str(model_path / "decoder-epoch-12-avg-2-chunk-16-left-64.onnx"),
                joiner=str(model_path / "joiner-epoch-12-avg-2-chunk-16-left-64.onnx"),
                keywords_file=str(selected_keywords),
                num_threads=num_threads,
                sample_rate=sample_rate_hz,
                keywords_threshold=threshold,
                provider="cpu",
            )
            self._stream: Any = self._spotter.create_stream()
        except (OSError, RuntimeError, TypeError, ValueError, ImportError) as exc:
            raise VoiceDependencyUnavailable(
                "configured sherpa-onnx KWS model could not be loaded"
            ) from exc
        self.model_path = model_path
        self.manifest_path = manifest_path
        self.keywords_path = selected_keywords
        self.sample_rate_hz = sample_rate_hz
        self.threshold = threshold
        self.model_name = SHERPA_ONNX_KWS_ARTIFACT

    @staticmethod
    def _load_manifest(model_path: Path, manifest_path: Path) -> dict[str, Any]:
        if not manifest_path.is_file():
            raise VoiceDependencyUnavailable("configured sherpa-onnx KWS manifest is missing")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise VoiceDependencyUnavailable(
                "configured sherpa-onnx KWS manifest is invalid"
            ) from exc
        if not isinstance(manifest, dict):
            raise VoiceDependencyUnavailable("configured sherpa-onnx KWS manifest is invalid")
        if (
            manifest.get("schema_version") != "phase-10-sherpa-onnx-kws/v1"
            or manifest.get("artifact") != SHERPA_ONNX_KWS_ARTIFACT
            or manifest.get("archive_sha256") != SHERPA_ONNX_KWS_ARCHIVE_SHA256
            or manifest.get("wake_word") != "Jarvis"
            or manifest.get("license") != "Apache-2.0"
            or manifest.get("keyword_line_count") != 1
        ):
            raise ValueError("sherpa-onnx KWS manifest identity or license is not accepted")
        keyword_file = manifest.get("keyword_file")
        if not isinstance(keyword_file, str) or Path(keyword_file).name != keyword_file:
            raise ValueError("sherpa-onnx KWS manifest keyword file is invalid")
        files = manifest.get("files")
        if not isinstance(files, dict):
            raise VoiceDependencyUnavailable("sherpa-onnx KWS manifest file hashes are missing")
        for name, expected in files.items():
            if not isinstance(name, str) or Path(name).name != name:
                raise ValueError("sherpa-onnx KWS manifest contains an unsafe file name")
            if not isinstance(expected, str) or len(expected) != 64:
                raise ValueError("sherpa-onnx KWS manifest contains an invalid file hash")
            path = model_path / name
            if not path.is_file() or _sha256_file(path) != expected:
                raise VoiceDependencyUnavailable(
                    f"sherpa-onnx KWS file verification failed: {name}"
                )
        if keyword_file not in files:
            raise VoiceDependencyUnavailable("sherpa-onnx KWS keyword file is not pinned")
        return manifest

    @property
    def available(self) -> bool:
        return True

    def detected(self, frame: AudioFrame) -> bool:
        if frame.sample_rate_hz != self.sample_rate_hz or frame.channels != 1:
            raise ValueError("sherpa-onnx KWS wake frame format is unsupported")
        try:
            numpy = importlib.import_module("numpy")
        except ImportError as exc:
            raise VoiceDependencyUnavailable("numpy is required by sherpa-onnx KWS") from exc
        samples = (
            numpy.frombuffer(frame.pcm_s16le, dtype=numpy.int16).astype(numpy.float32) / 32768.0
        )
        self._stream.accept_waveform(self.sample_rate_hz, samples)
        while self._spotter.is_ready(self._stream):
            self._spotter.decode_stream(self._stream)
        result = str(self._spotter.get_result(self._stream) or "").strip()
        if not result:
            return False
        self.reset()
        return " ".join(result.casefold().split()) == "jarvis"

    def reset(self) -> None:
        """Reset streaming state so prior speech cannot affect the next trial."""

        self._spotter.reset_stream(self._stream)


class PocketSphinxWakeWordDetector:
    """Free offline exact-``Jarvis`` fallback behind the wake adapter."""

    def __init__(self, *, sample_rate_hz: int = 16_000, threshold: float = 1e-20) -> None:
        if sample_rate_hz != 16_000:
            raise ValueError("PocketSphinx wake-word detection requires 16 kHz audio")
        if threshold <= 0:
            raise ValueError("PocketSphinx threshold must be positive")
        try:
            module = importlib.import_module("pocketsphinx")
        except ImportError as exc:
            raise VoiceDependencyUnavailable("pocketsphinx is not installed") from exc
        try:
            config = module.Config()
            config.set_float("-kws_threshold", threshold)
            self._decoder: Any = module.Decoder(config)
            self._decoder.add_keyphrase("jarvis", "jarvis")
            self._decoder.activate_search("jarvis")
            self._decoder.start_utt()
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise VoiceDependencyUnavailable("PocketSphinx wake model could not be loaded") from exc
        self.sample_rate_hz = sample_rate_hz
        self.threshold = threshold
        self.model_name = "pocketsphinx-default-en-us"

    @property
    def available(self) -> bool:
        return True

    def detected(self, frame: AudioFrame) -> bool:
        if frame.sample_rate_hz != self.sample_rate_hz or frame.channels != 1:
            raise ValueError("PocketSphinx wake frame format is unsupported")
        try:
            self._decoder.process_raw(frame.pcm_s16le, False, False)
            hypothesis = self._decoder.hyp()
            text = getattr(hypothesis, "hypstr", "") if hypothesis is not None else ""
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise VoiceDependencyUnavailable("PocketSphinx wake inference failed") from exc
        if not text:
            return False
        self.reset()
        return " ".join(str(text).casefold().split()) == "jarvis"

    def reset(self) -> None:
        """End and restart the bounded utterance state."""

        self._decoder.end_utt()
        self._decoder.start_utt()


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


class PersonalizedMfccDtwWakeWordDetector:
    """BMO-owned personalized exact-``Jarvis`` MFCC/DTW detector.

    The profile contains only derived MFCC templates. A short rolling PCM
    window exists solely in memory while streaming and is cleared on reset or
    detection. No pretrained wake or embedding weights are loaded.
    """

    def __init__(
        self,
        *,
        profile_path: Path,
        threshold: float = 0.42,
        min_template_matches: int = 2,
        max_buffer_seconds: float = 2.0,
        min_signal_rms: float = 0.002,
    ) -> None:
        if not profile_path.is_file():
            raise VoiceDependencyUnavailable("configured MFCC wake profile is missing")
        if not 0.0 < threshold <= 2.0:
            raise ValueError("MFCC DTW threshold must be between 0 and 2")
        if min_template_matches < 1 or min_template_matches > 4:
            raise ValueError("MFCC DTW template match count is unsupported")
        if max_buffer_seconds <= 0.0 or max_buffer_seconds > 3.0:
            raise ValueError("MFCC DTW buffer must be between 0 and 3 seconds")
        if min_signal_rms < 0.0:
            raise ValueError("MFCC DTW signal threshold cannot be negative")
        try:
            config, templates = read_mfcc_profile(profile_path)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise VoiceDependencyUnavailable("configured MFCC wake profile is invalid") from exc
        if min_template_matches > len(templates):
            raise ValueError("MFCC DTW requires more templates than the profile contains")
        self.profile_path = profile_path
        self.config = config
        self._templates = templates
        self.threshold = threshold
        self.min_template_matches = min_template_matches
        self.max_buffer_seconds = max_buffer_seconds
        self.min_signal_rms = min_signal_rms
        self.model_name = "personalized-mfcc-dtw-jarvis"
        self._buffer = bytearray()
        self.last_score = float("inf")

    @property
    def available(self) -> bool:
        return True

    def detected(self, frame: AudioFrame) -> bool:
        """Evaluate a bounded rolling window, including trailing command speech."""

        if frame.sample_rate_hz != self.config.sample_rate_hz or frame.channels != 1:
            raise ValueError("MFCC DTW wake frame format is unsupported")
        self._buffer.extend(frame.pcm_s16le)
        maximum_bytes = int(self.max_buffer_seconds * self.config.sample_rate_hz) * 2
        if len(self._buffer) > maximum_bytes:
            del self._buffer[: len(self._buffer) - maximum_bytes]
        numpy = importlib.import_module("numpy")
        samples = numpy.frombuffer(bytes(self._buffer), dtype=numpy.int16).astype(numpy.float32)
        samples /= numpy.float32(32768.0)
        if (
            samples.size == 0
            or float(numpy.sqrt(numpy.mean(samples * samples))) < self.min_signal_rms
        ):
            return False
        features = extract_mfcc(bytes(self._buffer), config=self.config)
        onset_frame = self._speech_onset_frame(samples, numpy)
        candidate_features = features[max(0, onset_frame - 2) :]
        distances = tuple(
            normalized_subsequence_dtw_distance_from(
                candidate_features,
                template,
                max_start_frames=8,
            )
            for template in self._templates
        )
        matches = sum(distance <= self.threshold for distance in distances)
        self.last_score = max(sorted(distances)[: self.min_template_matches])
        if matches < self.min_template_matches:
            return False
        best = sorted(distances)[: self.min_template_matches]
        self.reset()
        return max(best) <= self.threshold

    def _speech_onset_frame(self, samples: Any, numpy: Any) -> int:
        frame_length = self.config.frame_length
        hop_length = self.config.hop_length
        frame_count = max(1, 1 + max(0, (samples.size - frame_length) // hop_length))
        for index in range(frame_count):
            start = index * hop_length
            window = samples[start : start + frame_length]
            if (
                window.size
                and float(numpy.sqrt(numpy.mean(window * window))) >= self.min_signal_rms
            ):
                return index
        return 0

    def reset(self) -> None:
        """Clear the in-memory rolling window and all detector state."""

        self._buffer.clear()


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
        cuda_runtime_path: str | Path | Sequence[str | Path] | None = None,
    ) -> None:
        if device.casefold() != "cpu" and sys.platform == "win32":
            _load_cuda_runtime(cuda_runtime_path)
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


class FasterWhisperWakePhraseRecognizer:
    """English-specific short-phrase verifier separate from conversational STT."""

    def __init__(
        self,
        *,
        model: str,
        device: str = "cpu",
        compute_type: str = "int8",
        beam_size: int = 3,
        hotwords: str | None = None,
        cuda_runtime_path: str | Path | Sequence[str | Path] | None = None,
    ) -> None:
        if beam_size not in {1, 3, 5}:
            raise ValueError("wake verifier beam size must be 1, 3, or 5")
        if hotwords is not None and hotwords not in {PRIMARY_WAKE_PHRASE, "Jarvis"}:
            raise ValueError("wake verifier hotwords must be an exact supported phrase or disabled")
        if device.casefold() != "cpu" and sys.platform == "win32":
            _load_cuda_runtime(cuda_runtime_path)
        try:
            module = importlib.import_module("faster_whisper")
        except ImportError as exc:
            raise VoiceDependencyUnavailable("faster-whisper is not installed") from exc
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self.beam_size = 3
        self.hotwords: str | None = None
        self.set_decode_configuration(beam_size=beam_size, hotwords=hotwords)
        self._model: Any = module.WhisperModel(model, device=device, compute_type=compute_type)

    def set_decode_configuration(self, *, beam_size: int, hotwords: str | None) -> None:
        """Change only bounded wake decoding options; never sets a forced prefix."""

        if beam_size not in {1, 3, 5}:
            raise ValueError("wake verifier beam size must be 1, 3, or 5")
        if hotwords is not None and hotwords not in {PRIMARY_WAKE_PHRASE, "Jarvis"}:
            raise ValueError("wake verifier hotwords must be an exact supported phrase or disabled")
        self.beam_size = beam_size
        self.hotwords = hotwords

    def transcribe(self, frames: Sequence[AudioFrame]) -> str:
        try:
            numpy = importlib.import_module("numpy")
        except ImportError as exc:
            raise VoiceDependencyUnavailable("numpy is required by faster-whisper") from exc
        pcm = b"".join(frame.pcm_s16le for frame in frames)
        audio = numpy.frombuffer(pcm, dtype=numpy.int16).astype(numpy.float32) / 32768.0
        segments, _ = self._model.transcribe(
            audio,
            language="en",
            task="transcribe",
            condition_on_previous_text=False,
            without_timestamps=True,
            temperature=0.0,
            beam_size=self.beam_size,
            hotwords=self.hotwords,
            vad_filter=False,
            word_timestamps=False,
        )
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
    "SHERPA_ONNX_KWS_ARCHIVE_SHA256",
    "SHERPA_ONNX_KWS_ARTIFACT",
    "FasterWhisperRecognizer",
    "FasterWhisperWakePhraseRecognizer",
    "MicroWakeWordDetector",
    "OpenWakeWordDetector",
    "PersonalizedMfccDtwWakeWordDetector",
    "PocketSphinxWakeWordDetector",
    "SherpaOnnxPiperSynthesizer",
    "SherpaOnnxWakeWordDetector",
    "SileroVoiceActivityDetector",
    "VoiceDependencyUnavailable",
    "VoskWakeWordDetector",
    "installed_version",
    "resolve_cuda_runtime_paths",
]
