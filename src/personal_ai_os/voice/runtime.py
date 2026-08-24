"""Explicit Phase 10 local-runtime deployment contract."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from personal_ai_os.voice.adapters import (
    FasterWhisperRecognizer,
    MicroWakeWordDetector,
    OpenWakeWordDetector,
    SherpaOnnxPiperSynthesizer,
    SileroVoiceActivityDetector,
    VoskWakeWordDetector,
)
from personal_ai_os.voice.contracts import (
    AudioFrame,
    AudioPlayback,
    CoreConversationTransport,
    SpeechSynthesizer,
    WakeWordDetector,
)
from personal_ai_os.voice.pipecat_adapter import PipecatVoiceCoordinator
from personal_ai_os.voice.pipeline import JarvisVoicePipeline
from personal_ai_os.voice.sounddevice_backend import SoundDeviceBackend
from personal_ai_os.voice.streaming import CancellableTtsStream


@dataclass(frozen=True, slots=True)
class VoiceRuntimeConfig:
    """All model identities/paths are explicit; no home-directory inference."""

    wake_word_backend: Literal["vosk", "microwakeword", "openwakeword"] = "vosk"
    wake_word_model: str = "vosk-model-small-en-us-0.15"
    wake_word_model_path: Path | None = None
    wake_word_config_path: Path | None = None
    wake_word_threshold: float = 0.9
    stt_model: str = "medium"
    stt_device: str = "cuda"
    stt_compute_type: str = "float16"
    cuda_runtime_path: Path | None = None
    arabic_tts_model: Path | None = None
    arabic_tts_tokens: Path | None = None
    english_tts_model: Path | None = None
    english_tts_tokens: Path | None = None
    tts_data_dir: Path | None = None
    sample_rate_hz: int = 16_000

    def validate(self) -> None:
        """Require external model paths explicitly when TTS is enabled."""

        if not self.wake_word_model.strip():
            raise ValueError("wake_word_model is required")
        if self.wake_word_backend not in {"vosk", "microwakeword", "openwakeword"}:
            raise ValueError("unsupported wake-word backend")
        if self.wake_word_model_path is not None:
            if self.wake_word_backend == "vosk":
                valid_path = self.wake_word_model_path.is_dir()
            else:
                allowed_suffixes = (
                    {".tflite"}
                    if self.wake_word_backend == "microwakeword"
                    else {".onnx", ".tflite"}
                )
                valid_path = (
                    self.wake_word_model_path.suffix.casefold() in allowed_suffixes
                    and self.wake_word_model_path.is_file()
                )
            if not valid_path:
                raise ValueError("configured wake-word model does not exist")
        if self.wake_word_config_path is not None and not self.wake_word_config_path.is_file():
            raise ValueError("configured wake-word manifest does not exist")
        if self.arabic_tts_model is None or self.arabic_tts_tokens is None:
            raise ValueError("Arabic TTS model and tokens are required")
        if self.english_tts_model is None or self.english_tts_tokens is None:
            raise ValueError("English TTS model and tokens are required")
        if self.tts_data_dir is None:
            raise ValueError("shared espeak-ng data directory is required")
        if self.cuda_runtime_path is not None and not self.cuda_runtime_path.is_dir():
            raise ValueError("configured CUDA runtime directory does not exist")
        for name, path in (
            ("arabic_tts_model", self.arabic_tts_model),
            ("arabic_tts_tokens", self.arabic_tts_tokens),
            ("english_tts_model", self.english_tts_model),
            ("english_tts_tokens", self.english_tts_tokens),
            ("tts_data_dir", self.tts_data_dir),
        ):
            if path is not None and (
                not path.is_dir() if name == "tts_data_dir" else not path.is_file()
            ):
                raise ValueError(f"configured {name} does not exist")


class LanguageAwareSynthesizer:
    """Select the pinned local voice from response script, never from an LLM decision."""

    def __init__(self, arabic: SpeechSynthesizer, english: SpeechSynthesizer) -> None:
        self._arabic = arabic
        self._english = english

    def synthesize(self, text: str) -> Sequence[AudioFrame]:
        if any("\u0600" <= character <= "\u06ff" for character in text):
            return self._arabic.synthesize(text)
        return self._english.synthesize(text)


def build_local_runtime(
    config: VoiceRuntimeConfig,
    *,
    core: CoreConversationTransport,
    playback: AudioPlayback | None = None,
) -> tuple[JarvisVoicePipeline, str]:
    """Instantiate all local adapters; no adapter can call a model directly."""

    config.validate()
    if config.wake_word_model_path is None:
        raise ValueError("an explicit local Jarvis wake-word model path is required")
    if config.arabic_tts_model is None or config.arabic_tts_tokens is None:
        raise ValueError("Arabic TTS model and tokens are required for a production runtime")
    if config.english_tts_model is None or config.english_tts_tokens is None:
        raise ValueError("English TTS model and tokens are required for a production runtime")
    sound = playback or SoundDeviceBackend(sample_rate_hz=config.sample_rate_hz)
    model_path = config.wake_word_model_path
    if model_path is None:
        raise ValueError("an explicit local Jarvis wake-word model path is required")
    wake: WakeWordDetector
    if config.wake_word_backend == "vosk":
        wake = VoskWakeWordDetector(model_path=model_path, sample_rate_hz=config.sample_rate_hz)
    elif config.wake_word_backend == "microwakeword":
        wake = MicroWakeWordDetector(
            model_path=model_path,
            config_path=config.wake_word_config_path,
            threshold=config.wake_word_threshold,
        )
    else:
        wake = OpenWakeWordDetector(
            model_name=config.wake_word_model,
            model_path=model_path,
            threshold=config.wake_word_threshold,
        )
    vad = SileroVoiceActivityDetector()
    stt = FasterWhisperRecognizer(
        model=config.stt_model,
        device=config.stt_device,
        compute_type=config.stt_compute_type,
        cuda_runtime_path=(
            str(config.cuda_runtime_path) if config.cuda_runtime_path is not None else None
        ),
    )
    arabic_tts = SherpaOnnxPiperSynthesizer(
        model=str(config.arabic_tts_model),
        tokens=str(config.arabic_tts_tokens),
        data_dir=str(config.tts_data_dir),
    )
    english_tts = SherpaOnnxPiperSynthesizer(
        model=str(config.english_tts_model),
        tokens=str(config.english_tts_tokens),
        data_dir=str(config.tts_data_dir),
    )
    coordinator = PipecatVoiceCoordinator()
    turn_detector = coordinator.turn_detector()
    tts = LanguageAwareSynthesizer(arabic_tts, english_tts)
    tts_stream = CancellableTtsStream(synthesizer=tts, playback=sound)
    pipeline = JarvisVoicePipeline(
        wake_word=wake,
        vad=vad,
        stt=stt,
        core=core,
        tts=tts,
        playback=sound,
        turn_detector=turn_detector,
        tts_stream=tts_stream,
    )
    return pipeline, coordinator.version


__all__ = ["VoiceRuntimeConfig", "build_local_runtime"]
