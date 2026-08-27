"""Optional local engine adapters; imports stay behind product-owned boundaries."""

from __future__ import annotations

import array
import hashlib
import importlib
import importlib.metadata
import importlib.util
import os
import sys
from collections import deque
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from personal_ai_os.voice.contracts import AudioFrame
from personal_ai_os.voice.owner_verifier import (
    OwnerVerifierProfile,
    load_owner_verifier_profile,
)
from personal_ai_os.voice.wake_phrase import PRIMARY_WAKE_PHRASE
from personal_ai_os.voice.wake_policy import WakePolicyMode, WakeTemporalPolicy

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
        temporal_policy: WakePolicyMode = "threshold_crossing",
        deactivation_threshold: float = 0.0,
        vad_threshold: float | None = None,
        owner_verifier_profile: Path | None = None,
        base_candidate_invoke_threshold: float | None = None,
        final_owner_verifier_accept_threshold: float | None = None,
        allow_provisional_owner_verifier: bool = False,
    ) -> None:
        self._policy = WakeTemporalPolicy(
            threshold=threshold,
            window_frames=temporal_window_frames,
            required_hits=required_hits_in_window,
            mode=temporal_policy,
            deactivation_threshold=deactivation_threshold,
        )
        if vad_threshold is not None and not 0.0 <= vad_threshold <= 1.0:
            raise ValueError("openWakeWord VAD threshold must be between 0 and 1")
        if (
            base_candidate_invoke_threshold is not None
            and not 0.0 <= base_candidate_invoke_threshold <= 1.0
        ):
            raise ValueError("base candidate invoke threshold must be between 0 and 1")
        if (
            final_owner_verifier_accept_threshold is not None
            and not 0.0 <= final_owner_verifier_accept_threshold <= 1.0
        ):
            raise ValueError("final owner verifier threshold must be between 0 and 1")
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
        self.temporal_policy = temporal_policy
        self.deactivation_threshold = deactivation_threshold
        self.vad_threshold = vad_threshold
        self.owner_verifier_profile: OwnerVerifierProfile | None = None
        self.base_candidate_invoke_threshold = base_candidate_invoke_threshold
        self.final_owner_verifier_accept_threshold = final_owner_verifier_accept_threshold
        self._score_window: deque[float] = deque(maxlen=temporal_window_frames)
        self.expected_phrase = PRIMARY_WAKE_PHRASE
        self.last_score = 0.0
        model_kwargs: dict[str, Any] = {
            "wakeword_models": [selected_model],
            "inference_framework": "onnx",
        }
        if vad_threshold is not None:
            model_kwargs["vad_threshold"] = vad_threshold
        if owner_verifier_profile is not None:
            if model_path is None:
                raise VoiceDependencyUnavailable(
                    "owner wake verifier requires an explicit local base model"
                )
            actual_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()
            self.owner_verifier_profile = load_owner_verifier_profile(
                owner_verifier_profile,
                base_model_path=model_path,
                expected_base_sha256=actual_sha256,
                require_production_ready=not allow_provisional_owner_verifier,
            )
            contract = self.owner_verifier_profile.wake_contract
            if (
                base_candidate_invoke_threshold is not None
                and base_candidate_invoke_threshold != contract.base_candidate_invoke_threshold
            ):
                raise VoiceDependencyUnavailable(
                    "configured base candidate threshold differs from the owner verifier contract"
                )
            if (
                final_owner_verifier_accept_threshold is not None
                and contract.final_owner_verifier_accept_threshold is not None
                and final_owner_verifier_accept_threshold
                != contract.final_owner_verifier_accept_threshold
            ):
                raise VoiceDependencyUnavailable(
                    "configured final verifier threshold differs from the owner verifier contract"
                )
            resolved_final_threshold = contract.final_owner_verifier_accept_threshold
            if resolved_final_threshold is None and allow_provisional_owner_verifier:
                resolved_final_threshold = final_owner_verifier_accept_threshold
            if resolved_final_threshold is None:
                raise VoiceDependencyUnavailable(
                    "owner wake verifier final threshold is not calibrated"
                )
            self.threshold = resolved_final_threshold
            self._policy = WakeTemporalPolicy(
                threshold=self.threshold,
                window_frames=contract.temporal_window_frames,
                required_hits=contract.required_hits_in_window,
                mode=contract.temporal_policy,
                deactivation_threshold=contract.deactivation_threshold,
            )
            self.required_hits_in_window = contract.required_hits_in_window
            self.temporal_window_frames = contract.temporal_window_frames
            self.temporal_policy = contract.temporal_policy
            self.deactivation_threshold = contract.deactivation_threshold
            self._score_window = deque(maxlen=contract.temporal_window_frames)
            self.vad_threshold = contract.openwakeword_vad_threshold
            self.base_candidate_invoke_threshold = contract.base_candidate_invoke_threshold
            self.final_owner_verifier_accept_threshold = self.threshold
            if contract.openwakeword_vad_threshold is not None:
                raise VoiceDependencyUnavailable(
                    "owner verifier internal VAD is not production-approved"
                )
            model_kwargs.pop("vad_threshold", None)
            model_kwargs["custom_verifier_models"] = (
                self.owner_verifier_profile.custom_verifier_models
            )
            model_kwargs["custom_verifier_threshold"] = contract.base_candidate_invoke_threshold
        self._model = module.Model(**model_kwargs)

    @property
    def available(self) -> bool:
        return True

    def detected(self, frame: AudioFrame) -> bool:
        self._score_window.append(self.score(frame))
        return self._policy.accepts_window(tuple(self._score_window))

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
        self._score_window.clear()


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
    "FasterWhisperRecognizer",
    "FasterWhisperWakePhraseRecognizer",
    "OpenWakeWordDetector",
    "SherpaOnnxPiperSynthesizer",
    "SileroVoiceActivityDetector",
    "VoiceDependencyUnavailable",
    "installed_version",
    "resolve_cuda_runtime_paths",
]
