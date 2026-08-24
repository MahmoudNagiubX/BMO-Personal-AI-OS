"""Typed boundaries for local audio and the authenticated Core voice client."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class VoiceState(StrEnum):
    """Product-owned states; framework states never cross this boundary."""

    SLEEPING = "sleeping"
    WAKE_DETECTED = "wake_detected"
    LISTENING = "listening"
    SPEECH_DETECTED = "speech_detected"
    TRANSCRIBING = "transcribing"
    SENDING = "sending"
    WAITING_FOR_RESPONSE = "waiting_for_response"
    SPEAKING = "speaking"
    FOLLOW_UP_LISTENING = "follow_up_listening"
    INTERRUPTED = "interrupted"
    DEGRADED = "degraded"
    FAILED = "failed"
    MANUAL_CAPTURE = "manual_capture"


class VoiceLocalIntent(StrEnum):
    """Only local session controls; consequential commands remain Core-owned."""

    STOP = "stop"
    SLEEP = "sleep"
    REPEAT = "repeat"
    MUTE = "mute"


class ActivationSource(StrEnum):
    """Bounded local activation sources entering one voice pipeline."""

    WAKE_WORD = "wake_word"
    RIGHT_CTRL_DOUBLE_TAP = "right_ctrl_double_tap"
    PTT = "ptt"


class TurnDecision(StrEnum):
    """Turn boundary result; it never grants model or tool authority."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    FALLBACK_COMPLETE = "fallback_complete"


@dataclass(frozen=True, slots=True)
class AudioFrame:
    """A bounded in-memory PCM frame; raw data has no persistence API."""

    pcm_s16le: bytes
    sample_rate_hz: int = 16_000
    channels: int = 1

    def __post_init__(self) -> None:
        if not self.pcm_s16le:
            raise ValueError("audio frame must contain PCM bytes")
        if self.sample_rate_hz <= 0 or self.channels != 1:
            raise ValueError("audio frame metadata is unsupported")
        if len(self.pcm_s16le) % 2:
            raise ValueError("16-bit PCM must contain complete samples")

    @property
    def duration_seconds(self) -> float:
        return len(self.pcm_s16le) / 2 / self.sample_rate_hz


@dataclass(frozen=True, slots=True)
class CoreResponse:
    """Sanitized response returned by the existing authenticated Core API."""

    request_id: str
    text: str


@dataclass(frozen=True, slots=True)
class CoreResponseDelta:
    """Authenticated response text chunk; a final-ready event may be one chunk."""

    request_id: str
    text: str
    final: bool = False


@dataclass(frozen=True, slots=True)
class VoiceTurnResult:
    """Truthful result; text remains available when TTS/playback degrades."""

    state: VoiceState
    transcript: str | None = None
    response_text: str | None = None
    audio_played: bool = False
    local_intent: VoiceLocalIntent | None = None
    core_request_id: str | None = None
    degraded_reason: str | None = None


class WakeWordDetector(Protocol):
    """Local low-resource detector used only while sleeping."""

    @property
    def available(self) -> bool: ...

    def detected(self, frame: AudioFrame) -> bool: ...


class VoiceActivityDetector(Protocol):
    """Speech boundary and interruption detector, never a model authority."""

    def contains_speech(self, frames: Sequence[AudioFrame]) -> bool: ...


class SpeechRecognizer(Protocol):
    """Local multilingual STT; implementations must not persist audio."""

    def transcribe(self, frames: Sequence[AudioFrame]) -> str: ...


class SpeechSynthesizer(Protocol):
    """Local TTS adapter returning ephemeral PCM."""

    def synthesize(self, text: str) -> Sequence[AudioFrame]: ...


class AudioPlayback(Protocol):
    """Playback boundary with an explicit stop operation for barge-in."""

    def play(self, frames: Sequence[AudioFrame]) -> None: ...

    def stop(self) -> None: ...


class TurnDetector(Protocol):
    """Local end-of-turn decision layered on top of VAD."""

    def decide(
        self,
        frames: Sequence[AudioFrame],
        *,
        silence_seconds: float,
    ) -> TurnDecision: ...


class CoreConversationTransport(Protocol):
    """Authenticated transport to VENOM Core; no direct model method exists here."""

    def send(self, text: str, *, client_message_id: str) -> CoreResponse: ...

    def stream(self, text: str, *, client_message_id: str) -> Sequence[CoreResponseDelta]: ...

    def available(self) -> bool: ...


CoreSender = Callable[[str, str, str], CoreResponse]


__all__ = [
    "ActivationSource",
    "AudioFrame",
    "AudioPlayback",
    "CoreConversationTransport",
    "CoreResponse",
    "CoreResponseDelta",
    "CoreSender",
    "SpeechRecognizer",
    "SpeechSynthesizer",
    "TurnDecision",
    "TurnDetector",
    "VoiceActivityDetector",
    "VoiceLocalIntent",
    "VoiceState",
    "VoiceTurnResult",
    "WakeWordDetector",
]
