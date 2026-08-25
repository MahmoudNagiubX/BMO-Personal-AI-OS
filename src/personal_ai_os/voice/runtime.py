"""Explicit Phase 10 local-runtime deployment contract."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from personal_ai_os.voice.adapters import (
    FasterWhisperRecognizer,
    OpenWakeWordDetector,
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
from personal_ai_os.voice.owner_verifier import (
    default_owner_verifier_dir,
    load_owner_verifier_profile,
)
from personal_ai_os.voice.pipecat_adapter import PipecatVoiceCoordinator
from personal_ai_os.voice.pipeline import JarvisVoicePipeline
from personal_ai_os.voice.sounddevice_backend import SoundDeviceBackend
from personal_ai_os.voice.streaming import CancellableTtsStream
from personal_ai_os.voice.wake_phrase import (
    OPENWAKEWORD_MODEL_SHA256,
    PRIMARY_WAKE_PHRASE,
)
from personal_ai_os.voice.wake_policy import WakePolicyMode


@dataclass(frozen=True, slots=True)
class VoiceRuntimeConfig:
    """All model identities/paths are explicit; no home-directory inference."""

    wake_word_backend: Literal["openwakeword_owner_verifier"] = "openwakeword_owner_verifier"
    wake_phrase: str = PRIMARY_WAKE_PHRASE
    wake_word_model: str = "hey_jarvis_v0.1"
    wake_word_model_path: Path | None = None
    base_candidate_invoke_threshold: float | None = None
    final_owner_verifier_accept_threshold: float | None = None
    wake_word_required_hits: int | None = None
    wake_word_temporal_window_frames: int | None = None
    wake_word_temporal_policy: WakePolicyMode | None = None
    wake_word_deactivation_threshold: float | None = None
    wake_word_vad_threshold: float | None = None
    wake_word_expected_sha256: str | None = OPENWAKEWORD_MODEL_SHA256
    owner_verifier_profile: Path | None = None
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
        if self.wake_word_backend != "openwakeword_owner_verifier":
            raise ValueError("unsupported wake-word backend")
        if self.wake_phrase != PRIMARY_WAKE_PHRASE:
            raise ValueError("production wake phrase must remain Hey Jarvis")
        for name, value in (
            ("base_candidate_invoke_threshold", self.base_candidate_invoke_threshold),
            (
                "final_owner_verifier_accept_threshold",
                self.final_owner_verifier_accept_threshold,
            ),
            ("wake_word_deactivation_threshold", self.wake_word_deactivation_threshold),
        ):
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.wake_word_vad_threshold is not None:
            raise ValueError("openWakeWord internal VAD is not production-approved")
        if self.wake_word_expected_sha256 is not None and len(self.wake_word_expected_sha256) != 64:
            raise ValueError("wake-word checksum must be a SHA-256 hex digest")
        if self.wake_word_model_path is not None:
            valid_path = (
                self.wake_word_model_path.suffix.casefold() in {".onnx", ".tflite"}
                and self.wake_word_model_path.is_file()
            )
            if not valid_path:
                raise ValueError("configured wake-word model does not exist")
        if self.arabic_tts_model is None or self.arabic_tts_tokens is None:
            raise ValueError("Arabic TTS model and tokens are required")
        if self.english_tts_model is None or self.english_tts_tokens is None:
            raise ValueError("English TTS model and tokens are required")
        if self.tts_data_dir is None:
            raise ValueError("shared espeak-ng data directory is required")
        if self.owner_verifier_profile is None:
            raise ValueError("owner-specific wake verifier profile is required")
        if self.owner_verifier_profile != default_owner_verifier_dir():
            raise ValueError("owner wake verifier must use the approved local profile directory")
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

    if config.wake_word_model_path is None:
        raise ValueError("an explicit local Hey Jarvis wake-word model path is required")
    if config.arabic_tts_model is None or config.arabic_tts_tokens is None:
        raise ValueError("Arabic TTS model and tokens are required for a production runtime")
    if config.english_tts_model is None or config.english_tts_tokens is None:
        raise ValueError("English TTS model and tokens are required for a production runtime")
    config.validate()
    sound = playback or SoundDeviceBackend(sample_rate_hz=config.sample_rate_hz)
    model_path = config.wake_word_model_path
    vad = SileroVoiceActivityDetector()
    wake: WakeWordDetector
    if model_path is None:
        raise ValueError("the Hey Jarvis owner verifier requires an explicit model path")
    profile_path = config.owner_verifier_profile
    if profile_path is None:
        raise AssertionError("validated owner verifier profile unexpectedly missing")
    profile = load_owner_verifier_profile(
        profile_path,
        base_model_path=model_path,
        expected_base_sha256=config.wake_word_expected_sha256 or OPENWAKEWORD_MODEL_SHA256,
    )
    contract = profile.wake_contract
    if (
        config.base_candidate_invoke_threshold is not None
        and config.base_candidate_invoke_threshold != contract.base_candidate_invoke_threshold
    ):
        raise ValueError(
            "configured base candidate threshold differs from the owner verifier contract"
        )
    if (
        config.final_owner_verifier_accept_threshold is not None
        and config.final_owner_verifier_accept_threshold
        != contract.final_owner_verifier_accept_threshold
    ):
        raise ValueError(
            "configured final verifier threshold differs from the owner verifier contract"
        )
    if config.wake_word_required_hits is not None and (
        config.wake_word_required_hits != contract.required_hits_in_window
    ):
        raise ValueError("configured temporal hits differ from the owner verifier contract")
    if config.wake_word_temporal_window_frames is not None and (
        config.wake_word_temporal_window_frames != contract.temporal_window_frames
    ):
        raise ValueError("configured temporal window differs from the owner verifier contract")
    if config.wake_word_temporal_policy is not None and (
        config.wake_word_temporal_policy != contract.temporal_policy
    ):
        raise ValueError("configured temporal policy differs from the owner verifier contract")
    if config.wake_word_deactivation_threshold is not None and (
        config.wake_word_deactivation_threshold != contract.deactivation_threshold
    ):
        raise ValueError(
            "configured deactivation threshold differs from the owner verifier contract"
        )
    if contract.final_owner_verifier_accept_threshold is None:
        raise ValueError("owner verifier final threshold is not calibrated")
    wake = OpenWakeWordDetector(
        model_name=config.wake_word_model,
        model_path=model_path,
        threshold=contract.final_owner_verifier_accept_threshold,
        expected_sha256=config.wake_word_expected_sha256,
        required_hits_in_window=contract.required_hits_in_window,
        temporal_window_frames=contract.temporal_window_frames,
        temporal_policy=contract.temporal_policy,
        deactivation_threshold=contract.deactivation_threshold,
        vad_threshold=contract.openwakeword_vad_threshold,
        owner_verifier_profile=profile_path,
        base_candidate_invoke_threshold=contract.base_candidate_invoke_threshold,
        final_owner_verifier_accept_threshold=contract.final_owner_verifier_accept_threshold,
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
