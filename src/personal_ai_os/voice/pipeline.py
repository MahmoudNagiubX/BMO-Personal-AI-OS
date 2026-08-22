"""Hands-free JARVIS pipeline using the existing authenticated Core authority."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import suppress
from uuid import uuid4

from personal_ai_os.voice.commands import parse_local_intent
from personal_ai_os.voice.contracts import (
    AudioFrame,
    AudioPlayback,
    CoreConversationTransport,
    SpeechRecognizer,
    SpeechSynthesizer,
    VoiceActivityDetector,
    VoiceLocalIntent,
    VoiceState,
    VoiceTurnResult,
    WakeWordDetector,
)
from personal_ai_os.voice.privacy import BoundedAudioBuffer
from personal_ai_os.voice.state import VoiceEvent, VoiceStateMachine


class VoicePipelineError(RuntimeError):
    """A local pipeline failure that must not become a model fallback."""


class JarvisVoicePipeline:
    """Coordinate wake, VAD, STT, authenticated Core, TTS, and interruption."""

    def __init__(
        self,
        *,
        wake_word: WakeWordDetector,
        vad: VoiceActivityDetector,
        stt: SpeechRecognizer,
        core: CoreConversationTransport,
        tts: SpeechSynthesizer,
        playback: AudioPlayback,
        follow_up_timeout_seconds: float = 8.0,
        audio_buffer: BoundedAudioBuffer | None = None,
    ) -> None:
        if follow_up_timeout_seconds <= 0:
            raise ValueError("follow-up timeout must be positive")
        self.wake_word = wake_word
        self.vad = vad
        self.stt = stt
        self.core = core
        self.tts = tts
        self.playback = playback
        self.follow_up_timeout_seconds = follow_up_timeout_seconds
        self.machine = VoiceStateMachine()
        self.audio_buffer = audio_buffer or BoundedAudioBuffer()
        self._last_response: str | None = None
        self.muted = False

    @property
    def state(self) -> VoiceState:
        return self.machine.state

    def on_wake_frame(self, frame: AudioFrame) -> bool:
        """Run the tiny detector only while sleeping; never invokes STT/Core."""

        if self.state is not VoiceState.SLEEPING or not self.wake_word.available:
            return False
        if not self.wake_word.detected(frame):
            return False
        self.machine.transition(VoiceEvent.WAKE_WORD)
        self.machine.transition(VoiceEvent.WAKE_READY)
        return True

    def start_manual_capture(self) -> None:
        """Enable PTT only as a bounded fallback/debug path."""

        if self.state is not VoiceState.SLEEPING:
            raise VoicePipelineError("manual capture is available only while sleeping")
        self.machine.transition(VoiceEvent.MANUAL_CAPTURE)
        self.machine.transition(VoiceEvent.MANUAL_READY)

    def process_utterance(self, frames: Sequence[AudioFrame]) -> VoiceTurnResult:
        """Process one bounded utterance without persisting PCM or bypassing Core."""

        if self.state is VoiceState.SLEEPING:
            return VoiceTurnResult(state=self.state)
        if not frames or not self.vad.contains_speech(frames):
            if self.state is VoiceState.FOLLOW_UP_LISTENING:
                self.machine.transition(VoiceEvent.FOLLOW_UP_SILENCE)
            else:
                self._sleep()
            return VoiceTurnResult(state=self.state)
        self.machine.transition(VoiceEvent.SPEECH_START)
        try:
            with self.audio_buffer.lifetime() as buffer:
                for frame in frames:
                    buffer.append(frame)
                self.machine.transition(VoiceEvent.SPEECH_END)
                self.machine.transition(VoiceEvent.TRANSCRIPT_READY)
                transcript = self.stt.transcribe(buffer.take()).strip()
        except Exception as exc:
            self.audio_buffer.clear()
            self.machine.fail()
            return VoiceTurnResult(
                state=self.state, degraded_reason=f"stt_failed:{type(exc).__name__}"
            )
        if not transcript:
            self._sleep()
            return VoiceTurnResult(state=self.state)
        intent = parse_local_intent(transcript)
        if intent is not None:
            return self._local_intent(intent, transcript)
        self.machine.transition(VoiceEvent.CORE_SUBMITTED)
        try:
            response = self.core.send(transcript, client_message_id=str(uuid4()))
        except Exception as exc:
            self.machine.degrade()
            return VoiceTurnResult(
                state=self.state,
                transcript=transcript,
                degraded_reason=f"core_unavailable:{type(exc).__name__}",
            )
        self.machine.transition(VoiceEvent.RESPONSE_READY)
        self._last_response = response.text
        audio_played = False
        if not self.muted:
            try:
                self.playback.play(self.tts.synthesize(response.text))
                audio_played = True
            except Exception:
                # Text remains truthful and usable when local TTS/playback is unavailable.
                audio_played = False
        # A separate capture loop may have completed a barge-in while playback
        # was running.  Do not let the playback thread resurrect follow-up mode.
        if self.state is VoiceState.SPEAKING:
            self.machine.transition(VoiceEvent.FOLLOW_UP_READY)
        return VoiceTurnResult(
            state=self.state,
            transcript=transcript,
            response_text=response.text,
            audio_played=audio_played,
            core_request_id=response.request_id,
        )

    def barge_in(self) -> VoiceState:
        """Stop only this pipeline's playback and enter a fresh listening turn."""

        if self.state is not VoiceState.SPEAKING:
            return self.state
        self.playback.stop()
        self.machine.transition(VoiceEvent.BARGE_IN)
        self.machine.transition(VoiceEvent.INTERRUPTION_READY)
        return self.state

    def silence_timeout(self) -> VoiceState:
        """End the bounded follow-up window and return to wake-word-only idle."""

        if self.state is VoiceState.FOLLOW_UP_LISTENING:
            self.machine.transition(VoiceEvent.FOLLOW_UP_SILENCE)
        return self.state

    def sleep(self) -> VoiceState:
        """Apply the local sleep command and stop active playback."""

        if self.state is VoiceState.SPEAKING:
            self.playback.stop()
        if self.state is not VoiceState.SLEEPING:
            self.machine.state = VoiceState.SLEEPING
        self.audio_buffer.clear()
        return self.state

    def _local_intent(self, intent: VoiceLocalIntent, transcript: str) -> VoiceTurnResult:
        if intent in {VoiceLocalIntent.STOP, VoiceLocalIntent.SLEEP}:
            self.sleep()
        elif intent is VoiceLocalIntent.MUTE:
            self.muted = True
            self.sleep()
        elif intent is VoiceLocalIntent.REPEAT:
            if self._last_response is not None and not self.muted:
                with suppress(Exception):
                    self.playback.play(self.tts.synthesize(self._last_response))
            self.machine.state = VoiceState.FOLLOW_UP_LISTENING
        return VoiceTurnResult(state=self.state, transcript=transcript, local_intent=intent)

    def _sleep(self) -> None:
        self.machine.state = VoiceState.SLEEPING
        self.audio_buffer.clear()


__all__ = ["JarvisVoicePipeline", "VoicePipelineError"]
