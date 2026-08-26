"""Deterministic JARVIS voice-session state machine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from personal_ai_os.voice.contracts import VoiceState


class VoiceEvent(StrEnum):
    WAKE_WORD = "wake_word"
    WAKE_READY = "wake_ready"
    MANUAL_CAPTURE = "manual_capture"
    MANUAL_READY = "manual_ready"
    KEYBOARD_ACTIVATION = "keyboard_activation"
    SPEECH_START = "speech_start"
    SPEECH_END = "speech_end"
    TRANSCRIPT_READY = "transcript_ready"
    CORE_SUBMITTED = "core_submitted"
    RESPONSE_READY = "response_ready"
    FOLLOW_UP_READY = "follow_up_ready"
    FOLLOW_UP_SILENCE = "follow_up_silence"
    BARGE_IN = "barge_in"
    INTERRUPTION_READY = "interruption_ready"
    LOCAL_SLEEP = "local_sleep"
    DEGRADED = "degraded"
    FAILURE = "failure"
    RECOVER = "recover"


class InvalidVoiceTransition(RuntimeError):
    """Raised when an event would violate the product-owned state graph."""


_TRANSITIONS: dict[tuple[VoiceState, VoiceEvent], VoiceState] = {
    (VoiceState.SLEEPING, VoiceEvent.WAKE_WORD): VoiceState.WAKE_DETECTED,
    (VoiceState.WAKE_DETECTED, VoiceEvent.WAKE_READY): VoiceState.LISTENING,
    (VoiceState.SLEEPING, VoiceEvent.MANUAL_CAPTURE): VoiceState.MANUAL_CAPTURE,
    (VoiceState.MANUAL_CAPTURE, VoiceEvent.MANUAL_READY): VoiceState.LISTENING,
    (VoiceState.SLEEPING, VoiceEvent.KEYBOARD_ACTIVATION): VoiceState.LISTENING,
    (VoiceState.LISTENING, VoiceEvent.SPEECH_START): VoiceState.SPEECH_DETECTED,
    (VoiceState.MANUAL_CAPTURE, VoiceEvent.SPEECH_START): VoiceState.SPEECH_DETECTED,
    (VoiceState.FOLLOW_UP_LISTENING, VoiceEvent.SPEECH_START): VoiceState.SPEECH_DETECTED,
    (VoiceState.SPEECH_DETECTED, VoiceEvent.SPEECH_END): VoiceState.TRANSCRIBING,
    (VoiceState.TRANSCRIBING, VoiceEvent.TRANSCRIPT_READY): VoiceState.SENDING,
    (VoiceState.SENDING, VoiceEvent.CORE_SUBMITTED): VoiceState.WAITING_FOR_RESPONSE,
    (VoiceState.WAITING_FOR_RESPONSE, VoiceEvent.RESPONSE_READY): VoiceState.SPEAKING,
    (VoiceState.SPEAKING, VoiceEvent.FOLLOW_UP_READY): VoiceState.FOLLOW_UP_LISTENING,
    (VoiceState.SPEAKING, VoiceEvent.BARGE_IN): VoiceState.INTERRUPTED,
    (VoiceState.INTERRUPTED, VoiceEvent.INTERRUPTION_READY): VoiceState.LISTENING,
    (VoiceState.FOLLOW_UP_LISTENING, VoiceEvent.FOLLOW_UP_SILENCE): VoiceState.SLEEPING,
    (VoiceState.LISTENING, VoiceEvent.LOCAL_SLEEP): VoiceState.SLEEPING,
    (VoiceState.WAKE_DETECTED, VoiceEvent.LOCAL_SLEEP): VoiceState.SLEEPING,
    (VoiceState.FOLLOW_UP_LISTENING, VoiceEvent.LOCAL_SLEEP): VoiceState.SLEEPING,
    (VoiceState.SPEAKING, VoiceEvent.LOCAL_SLEEP): VoiceState.SLEEPING,
    (VoiceState.DEGRADED, VoiceEvent.RECOVER): VoiceState.SLEEPING,
    (VoiceState.FAILED, VoiceEvent.RECOVER): VoiceState.SLEEPING,
}


@dataclass(slots=True)
class VoiceStateMachine:
    """Small explicit state machine with no implicit fallback transitions."""

    state: VoiceState = VoiceState.SLEEPING
    history: list[VoiceState] = field(init=False)

    def __post_init__(self) -> None:
        self.history = [self.state]

    def transition(self, event: VoiceEvent) -> VoiceState:
        """Apply one declared event or reject the illegal transition."""

        next_state = _TRANSITIONS.get((self.state, event))
        if next_state is None:
            raise InvalidVoiceTransition(f"{self.state.value} cannot accept {event.value}")
        self.state = next_state
        self.history.append(next_state)
        return next_state

    def degrade(self) -> VoiceState:
        """Enter bounded degraded mode from any active state."""

        if self.state not in {VoiceState.SLEEPING, VoiceState.DEGRADED}:
            self.state = VoiceState.DEGRADED
            self.history.append(self.state)
        return self.state

    def fail(self) -> VoiceState:
        """Enter terminal-for-this-session failure without hiding the cause."""

        self.state = VoiceState.FAILED
        if not self.history or self.history[-1] is not VoiceState.FAILED:
            self.history.append(self.state)
        return self.state

    def recover(self) -> VoiceState:
        """Return only through the explicit recovery edge."""

        return self.transition(VoiceEvent.RECOVER)

    def force_state(self, state: VoiceState) -> VoiceState:
        """Record a bounded local reset when no graph edge represents cleanup."""

        self.state = state
        if not self.history or self.history[-1] is not state:
            self.history.append(state)
        return state


__all__ = ["InvalidVoiceTransition", "VoiceEvent", "VoiceStateMachine"]
