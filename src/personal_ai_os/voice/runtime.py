"""Explicit Phase 10 local-runtime deployment contract."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from personal_ai_os.voice.adapters import (
    FasterWhisperRecognizer,
    FasterWhisperWakePhraseRecognizer,
    MicroWakeWordDetector,
    OpenWakeWordDetector,
    PersonalizedMfccDtwWakeWordDetector,
    PocketSphinxWakeWordDetector,
    SherpaOnnxPiperSynthesizer,
    SherpaOnnxWakeWordDetector,
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
from personal_ai_os.voice.wake_cascade import (
    LazyWakeCandidateVerifier,
    WakeCascadeDetector,
    WhisperWakePhraseVerifier,
)
from personal_ai_os.voice.wake_phrase import (
    OPENWAKEWORD_MODEL_SHA256,
    PRIMARY_WAKE_PHRASE,
)


@dataclass(frozen=True, slots=True)
class VoiceRuntimeConfig:
    """All model identities/paths are explicit; no home-directory inference."""

    wake_word_backend: Literal[
        "openwakeword",
        "cascade_openwakeword_whisper",
        "vad_whisper",
        "cascade_vad_whisper",
        "cascade_mfcc_whisper",
        "personalized_mfcc_dtw",
        "sherpa_onnx_kws",
        "pocketsphinx",
        "vosk",
        "microwakeword",
    ] = "openwakeword"
    wake_phrase: str = PRIMARY_WAKE_PHRASE
    wake_word_model: str = "hey_jarvis_v0.1"
    wake_word_model_path: Path | None = None
    wake_word_config_path: Path | None = None
    wake_word_keywords_path: Path | None = None
    wake_word_threshold: float = 0.5
    wake_word_required_hits: int = 1
    wake_word_temporal_window_frames: int = 3
    wake_word_expected_sha256: str | None = OPENWAKEWORD_MODEL_SHA256
    wake_verifier_model: str = "base.en"
    wake_verifier_device: str = "cuda"
    wake_verifier_compute_type: str = "float16"
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
        if self.wake_word_backend not in {
            "openwakeword",
            "cascade_openwakeword_whisper",
            "vad_whisper",
            "cascade_vad_whisper",
            "cascade_mfcc_whisper",
            "personalized_mfcc_dtw",
            "sherpa_onnx_kws",
            "pocketsphinx",
            "vosk",
            "microwakeword",
        }:
            raise ValueError("unsupported wake-word backend")
        if self.wake_phrase != PRIMARY_WAKE_PHRASE:
            raise ValueError("production wake phrase must remain Hey Jarvis")
        if not 0.0 <= self.wake_word_threshold <= 1.0:
            raise ValueError("wake-word threshold must be between 0 and 1")
        if not 1 <= self.wake_word_required_hits <= self.wake_word_temporal_window_frames:
            raise ValueError("wake-word temporal hit bounds are invalid")
        if self.wake_word_expected_sha256 is not None and len(self.wake_word_expected_sha256) != 64:
            raise ValueError("wake-word checksum must be a SHA-256 hex digest")
        if self.wake_word_model_path is not None:
            if self.wake_word_backend == "personalized_mfcc_dtw":
                valid_path = (
                    self.wake_word_model_path.suffix.casefold() == ".json"
                    and self.wake_word_model_path.is_file()
                )
            elif self.wake_word_backend in {"sherpa_onnx_kws", "vosk"}:
                valid_path = self.wake_word_model_path.is_dir()
            elif self.wake_word_backend in {
                "vad_whisper",
                "cascade_vad_whisper",
            }:
                valid_path = self.wake_word_model_path.exists()
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
        if (
            self.wake_word_backend in {"personalized_mfcc_dtw", "cascade_mfcc_whisper"}
            and self.wake_word_model_path is None
        ):
            raise ValueError(
                "the MFCC wake path requires an explicit local Jarvis wake-word model profile"
            )
        if self.wake_word_backend == "sherpa_onnx_kws":
            if self.wake_word_config_path is None:
                raise ValueError(
                    "sherpa-onnx KWS requires an explicit local Jarvis wake-word model manifest"
                )
            if (
                self.wake_word_keywords_path is not None
                and not self.wake_word_keywords_path.is_file()
            ):
                raise ValueError("configured sherpa-onnx keyword file does not exist")


class VadWakeCandidate(WakeWordDetector):
    """Bridge Silero VAD into a bounded rolling streaming candidate."""

    def __init__(
        self,
        vad: SileroVoiceActivityDetector,
        *,
        sample_rate_hz: int = 16_000,
        window_seconds: float = 0.64,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("VAD candidate window must be positive")
        if sample_rate_hz <= 0:
            raise ValueError("VAD candidate sample rate must be positive")
        self._vad = vad
        self._max_bytes = int(window_seconds * sample_rate_hz) * 2
        self._frames: deque[AudioFrame] = deque()

    @property
    def available(self) -> bool:
        return True

    def detected(self, frame: AudioFrame) -> bool:
        self._frames.append(frame)
        total = sum(len(item.pcm_s16le) for item in self._frames)
        while self._frames and total > self._max_bytes:
            total -= len(self._frames.popleft().pcm_s16le)
        return self._vad.contains_speech(tuple(self._frames))

    def reset(self) -> None:
        self._frames.clear()


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
    if config.wake_word_model_path is None and config.wake_word_backend not in {
        "pocketsphinx",
        "vad_whisper",
        "cascade_vad_whisper",
    }:
        raise ValueError("an explicit local Hey Jarvis wake-word model path is required")
    if config.arabic_tts_model is None or config.arabic_tts_tokens is None:
        raise ValueError("Arabic TTS model and tokens are required for a production runtime")
    if config.english_tts_model is None or config.english_tts_tokens is None:
        raise ValueError("English TTS model and tokens are required for a production runtime")
    sound = playback or SoundDeviceBackend(sample_rate_hz=config.sample_rate_hz)
    model_path = config.wake_word_model_path
    vad = SileroVoiceActivityDetector()
    wake: WakeWordDetector
    candidate: WakeWordDetector
    if config.wake_word_backend in {"vad_whisper", "cascade_vad_whisper"}:
        candidate = VadWakeCandidate(vad, sample_rate_hz=config.sample_rate_hz)
        verifier = LazyWakeCandidateVerifier(
            lambda: WhisperWakePhraseVerifier(
                FasterWhisperWakePhraseRecognizer(
                    model=config.wake_verifier_model,
                    device=config.wake_verifier_device,
                    compute_type=config.wake_verifier_compute_type,
                    cuda_runtime_path=(
                        str(config.cuda_runtime_path)
                        if config.cuda_runtime_path is not None
                        else None
                    ),
                ),
                wake_word=config.wake_phrase,
            )
        )
        wake = WakeCascadeDetector(
            candidate=candidate,
            verifier=verifier,
            vad=None,
            max_candidate_seconds=1.8,
            min_speech_seconds=0.32,
            verification_window_seconds=0.8,
            verification_retry_interval_seconds=0.16,
            max_verification_attempts=4,
        )
    elif config.wake_word_backend == "cascade_mfcc_whisper":
        if model_path is None:
            raise ValueError("the wake cascade requires an explicit MFCC candidate profile")
        candidate = PersonalizedMfccDtwWakeWordDetector(
            profile_path=model_path,
            threshold=config.wake_word_threshold,
        )
        verifier = LazyWakeCandidateVerifier(
            lambda: WhisperWakePhraseVerifier(
                FasterWhisperWakePhraseRecognizer(
                    model=config.wake_verifier_model,
                    device=config.wake_verifier_device,
                    compute_type=config.wake_verifier_compute_type,
                    cuda_runtime_path=(
                        str(config.cuda_runtime_path)
                        if config.cuda_runtime_path is not None
                        else None
                    ),
                ),
                wake_word=config.wake_phrase,
            )
        )
        wake = WakeCascadeDetector(
            candidate=candidate,
            verifier=verifier,
            vad=vad,
            max_candidate_seconds=1.8,
            min_speech_seconds=0.32,
            verification_window_seconds=0.8,
            verification_retry_interval_seconds=0.16,
            max_verification_attempts=4,
        )
    elif config.wake_word_backend == "cascade_openwakeword_whisper":
        if model_path is None:
            raise ValueError("the Hey Jarvis wake cascade requires an explicit model path")
        candidate = OpenWakeWordDetector(
            model_name=config.wake_word_model,
            model_path=model_path,
            threshold=config.wake_word_threshold,
            expected_sha256=config.wake_word_expected_sha256,
            required_hits_in_window=config.wake_word_required_hits,
            temporal_window_frames=config.wake_word_temporal_window_frames,
        )
        verifier = LazyWakeCandidateVerifier(
            lambda: WhisperWakePhraseVerifier(
                FasterWhisperWakePhraseRecognizer(
                    model=config.wake_verifier_model,
                    device=config.wake_verifier_device,
                    compute_type=config.wake_verifier_compute_type,
                    cuda_runtime_path=(
                        str(config.cuda_runtime_path)
                        if config.cuda_runtime_path is not None
                        else None
                    ),
                ),
                wake_word=config.wake_phrase,
            )
        )
        wake = WakeCascadeDetector(
            candidate=candidate,
            verifier=verifier,
            vad=None,
            max_candidate_seconds=1.8,
            min_speech_seconds=0.16,
            verification_window_seconds=0.8,
            verification_retry_interval_seconds=0.16,
            max_verification_attempts=4,
        )
    elif config.wake_word_backend == "personalized_mfcc_dtw":
        if model_path is None:
            raise ValueError(
                "personalized MFCC DTW requires an explicit local Jarvis wake-word model profile"
            )
        wake = PersonalizedMfccDtwWakeWordDetector(
            profile_path=model_path,
            threshold=config.wake_word_threshold,
        )
    elif config.wake_word_backend == "sherpa_onnx_kws":
        if model_path is None:
            raise ValueError("sherpa-onnx KWS requires an explicit model path")
        wake = SherpaOnnxWakeWordDetector(
            model_path=model_path,
            manifest_path=cast(Path, config.wake_word_config_path),
            keywords_path=config.wake_word_keywords_path,
            sample_rate_hz=config.sample_rate_hz,
            threshold=config.wake_word_threshold,
        )
    elif config.wake_word_backend == "pocketsphinx":
        wake = PocketSphinxWakeWordDetector(
            sample_rate_hz=config.sample_rate_hz,
            threshold=config.wake_word_threshold,
        )
    elif config.wake_word_backend == "vosk":
        if model_path is None:
            raise ValueError("Vosk requires an explicit model path")
        wake = VoskWakeWordDetector(model_path=model_path, sample_rate_hz=config.sample_rate_hz)
    elif config.wake_word_backend == "microwakeword":
        if model_path is None:
            raise ValueError("microWakeWord requires an explicit model path")
        wake = MicroWakeWordDetector(
            model_path=model_path,
            config_path=config.wake_word_config_path,
            threshold=config.wake_word_threshold,
        )
    else:
        if model_path is None:
            raise ValueError("openWakeWord requires an explicit model path")
        wake = OpenWakeWordDetector(
            model_name=config.wake_word_model,
            model_path=model_path,
            threshold=config.wake_word_threshold,
            expected_sha256=config.wake_word_expected_sha256,
            required_hits_in_window=config.wake_word_required_hits,
            temporal_window_frames=config.wake_word_temporal_window_frames,
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


__all__ = ["VoiceRuntimeConfig", "build_local_runtime"]
