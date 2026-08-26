"""Explicit Phase 10 local-runtime deployment contract."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from personal_ai_os.voice.adapters import (
    FasterWhisperRecognizer,
    FasterWhisperWakePhraseRecognizer,
    SherpaOnnxPiperSynthesizer,
    SileroVoiceActivityDetector,
)
from personal_ai_os.voice.contracts import (
    AudioFrame,
    AudioPlayback,
    CoreConversationTransport,
    SpeechSynthesizer,
    WakeWordDetector,
)
from personal_ai_os.voice.conversation_loop import JarvisConversationLoop
from personal_ai_os.voice.pipecat_adapter import PipecatVoiceCoordinator
from personal_ai_os.voice.pipeline import JarvisVoicePipeline
from personal_ai_os.voice.sounddevice_backend import SoundDeviceBackend
from personal_ai_os.voice.speech_gated_wake import (
    DEFAULT_INITIAL_VERIFICATION_SECONDS,
    DEFAULT_MAX_CANDIDATE_SECONDS,
    DEFAULT_MAX_VERIFICATION_ATTEMPTS,
    DEFAULT_MIN_SPEECH_SECONDS,
    DEFAULT_RETRY_INTERVAL_SECONDS,
    DEFAULT_SPEECH_END_SILENCE_SECONDS,
    DEFAULT_VAD_WINDOW_SECONDS,
    SpeechGatedHeyJarvisDetector,
)
from personal_ai_os.voice.streaming import CancellableTtsStream
from personal_ai_os.voice.wake_cascade import WhisperWakePhraseVerifier
from personal_ai_os.voice.wake_phrase import PRIMARY_WAKE_PHRASE


@dataclass(frozen=True, slots=True)
class VoiceRuntimeConfig:
    """All model identities/paths are explicit; no home-directory inference."""

    wake_word_backend: Literal["speech_gated_faster_whisper"] = "speech_gated_faster_whisper"
    wake_phrase: str = PRIMARY_WAKE_PHRASE
    wake_word_model: str = "base.en"
    wake_word_device: str = "cpu"
    wake_word_compute_type: str = "int8"
    wake_word_beam_size: int = 1
    wake_word_hotwords: str | None = None
    wake_word_max_candidate_seconds: float = DEFAULT_MAX_CANDIDATE_SECONDS
    wake_word_vad_window_seconds: float = DEFAULT_VAD_WINDOW_SECONDS
    wake_word_min_speech_seconds: float = DEFAULT_MIN_SPEECH_SECONDS
    wake_word_initial_verification_seconds: float = DEFAULT_INITIAL_VERIFICATION_SECONDS
    wake_word_retry_interval_seconds: float = DEFAULT_RETRY_INTERVAL_SECONDS
    wake_word_max_verification_attempts: int = DEFAULT_MAX_VERIFICATION_ATTEMPTS
    wake_word_speech_end_silence_seconds: float = DEFAULT_SPEECH_END_SILENCE_SECONDS
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
        if self.wake_word_backend != "speech_gated_faster_whisper":
            raise ValueError("unsupported wake-word backend")
        if self.wake_phrase != PRIMARY_WAKE_PHRASE:
            raise ValueError("production wake phrase must remain Hey Jarvis")
        if self.wake_word_device.casefold() not in {"cpu", "cuda"}:
            raise ValueError("wake-word device must be cpu or cuda")
        if self.wake_word_compute_type not in {"int8", "float16"}:
            raise ValueError("wake-word compute type must be int8 or float16")
        if self.wake_word_beam_size not in {1, 3, 5}:
            raise ValueError("wake-word beam size must be 1, 3, or 5")
        if self.wake_word_hotwords not in {None, PRIMARY_WAKE_PHRASE, "Jarvis"}:
            raise ValueError("wake-word hotwords must be disabled or an exact supported phrase")
        for name in (
            "wake_word_max_candidate_seconds",
            "wake_word_vad_window_seconds",
            "wake_word_min_speech_seconds",
            "wake_word_initial_verification_seconds",
            "wake_word_retry_interval_seconds",
            "wake_word_speech_end_silence_seconds",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.wake_word_vad_window_seconds > self.wake_word_max_candidate_seconds:
            raise ValueError("wake VAD window cannot exceed candidate window")
        if self.wake_word_min_speech_seconds > self.wake_word_initial_verification_seconds:
            raise ValueError("wake minimum speech cannot exceed initial verification window")
        if self.wake_word_initial_verification_seconds > self.wake_word_max_candidate_seconds:
            raise ValueError("wake initial verification cannot exceed candidate window")
        if self.wake_word_max_verification_attempts <= 0:
            raise ValueError("wake verification attempt bound must be positive")
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

    if config.arabic_tts_model is None or config.arabic_tts_tokens is None:
        raise ValueError("Arabic TTS model and tokens are required for a production runtime")
    if config.english_tts_model is None or config.english_tts_tokens is None:
        raise ValueError("English TTS model and tokens are required for a production runtime")
    config.validate()
    sound = playback or SoundDeviceBackend(sample_rate_hz=config.sample_rate_hz)
    vad = SileroVoiceActivityDetector()
    wake_recognizer = FasterWhisperWakePhraseRecognizer(
        model=config.wake_word_model,
        device=config.wake_word_device,
        compute_type=config.wake_word_compute_type,
        beam_size=config.wake_word_beam_size,
        hotwords=config.wake_word_hotwords,
        cuda_runtime_path=(
            str(config.cuda_runtime_path) if config.cuda_runtime_path is not None else None
        ),
    )
    wake: WakeWordDetector = SpeechGatedHeyJarvisDetector(
        vad=vad,
        verifier=WhisperWakePhraseVerifier(wake_recognizer, wake_word=config.wake_phrase),
        max_candidate_seconds=config.wake_word_max_candidate_seconds,
        vad_window_seconds=config.wake_word_vad_window_seconds,
        min_speech_seconds=config.wake_word_min_speech_seconds,
        initial_verification_seconds=config.wake_word_initial_verification_seconds,
        retry_interval_seconds=config.wake_word_retry_interval_seconds,
        max_verification_attempts=config.wake_word_max_verification_attempts,
        speech_end_silence_seconds=config.wake_word_speech_end_silence_seconds,
    )
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


def build_local_conversation_loop(
    config: VoiceRuntimeConfig,
    *,
    core: CoreConversationTransport,
    playback: AudioPlayback | None = None,
) -> tuple[JarvisConversationLoop, str]:
    """Build the local adapters and their bounded live conversation loop."""

    pipeline, coordinator_version = build_local_runtime(config, core=core, playback=playback)
    return JarvisConversationLoop(pipeline), coordinator_version


__all__ = [
    "VoiceRuntimeConfig",
    "build_local_conversation_loop",
    "build_local_runtime",
]
