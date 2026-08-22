"""Exact local voice-session commands; no general command execution."""

from __future__ import annotations

from personal_ai_os.voice.contracts import VoiceLocalIntent

_COMMANDS: dict[str, VoiceLocalIntent] = {
    "stop": VoiceLocalIntent.STOP,
    "stop speaking": VoiceLocalIntent.STOP,
    "cancel": VoiceLocalIntent.STOP,
    "go to sleep": VoiceLocalIntent.SLEEP,
    "sleep": VoiceLocalIntent.SLEEP,
    "repeat": VoiceLocalIntent.REPEAT,
    "say that again": VoiceLocalIntent.REPEAT,
    "mute": VoiceLocalIntent.MUTE,
    "mute voice": VoiceLocalIntent.MUTE,
}


def parse_local_intent(transcript: str) -> VoiceLocalIntent | None:
    """Match only a fixed normalized phrase, never arbitrary shell-like text."""

    return _COMMANDS.get(" ".join(transcript.casefold().strip().split()))


__all__ = ["parse_local_intent"]
