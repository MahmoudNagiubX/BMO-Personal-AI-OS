"""Hands-free JARVIS pipeline using the existing authenticated Core authority."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import suppress
from uuid import uuid4

from personal_ai_os.voice.activation import ActivationRouter
from personal_ai_os.voice.commands import parse_local_intent
from personal_ai_os.voice.contracts import (
    ActivationSource,
    AudioFrame,
    AudioPlayback,
    CoreConversationTransport,
    CoreResponse,
    SpeechRecognizer,
    SpeechSynthesizer,
    TurnDecision,
    TurnDetector,
    VoiceActivityDetector,
    VoiceLocalIntent,
    VoiceState,
    VoiceTurnResult,
    WakeWordDetector,
)
from personal_ai_os.voice.privacy import BoundedAudioBuffer, InMemoryPreRoll
from personal_ai_os.voice.state import VoiceEvent, VoiceStateMachine
from personal_ai_os.voice.streaming import CancellableTtsStream
from personal_ai_os.voice.wake_cascade import strip_leading_wake_phrase


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
        pre_roll: InMemoryPreRoll | None = None,
        turn_detector: TurnDetector | None = None,
        tts_stream: CancellableTtsStream | None = None,
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
        self.pre_roll = pre_roll or InMemoryPreRoll()
        self.turn_detector = turn_detector
        self.tts_stream = tts_stream
        self.activation_router = ActivationRouter(self.activate)
        self._last_response: str | None = None
        self.muted = False

    @property
    def state(self) -> VoiceState:
        return self.machine.state

    def _reset_detector(self) -> None:
        """Reset wake detector state if supported by the active backend."""

        reset_method = getattr(self.wake_word, "reset", None)
        if callable(reset_method):
            reset_method()

    def on_wake_frame(self, frame: AudioFrame) -> bool:
        """Run the tiny detector only while sleeping; never invokes STT/Core."""

        if self.state is not VoiceState.SLEEPING or not self.wake_word.available:
            return False
        if not self.wake_word.detected(frame):
            return False
        self.machine.transition(VoiceEvent.WAKE_WORD)
        self.machine.transition(VoiceEvent.WAKE_READY)
        return True

    def on_capture_frame(self, frame: AudioFrame) -> bool:
        """Feed one live frame through pre-roll and wake detection only while sleeping."""

        if self.state is not VoiceState.SLEEPING:
            return False
        self.pre_roll.append(frame)
        return self.on_wake_frame(frame)

    def start_keyboard_capture(self) -> None:
        """Activate LISTENING from the bounded Right-Ctrl double-tap path."""

        if self.state is not VoiceState.SLEEPING:
            raise VoicePipelineError("keyboard activation is available only while sleeping")
        self.pre_roll.clear()
        self._reset_detector()
        self.machine.transition(VoiceEvent.KEYBOARD_ACTIVATION)

    def start_manual_capture(self) -> None:
        """Enable PTT only as a bounded fallback/debug path."""

        if self.state is not VoiceState.SLEEPING:
            raise VoicePipelineError("manual capture is available only while sleeping")
        self.pre_roll.clear()
        self._reset_detector()
        self.machine.transition(VoiceEvent.MANUAL_CAPTURE)
        self.machine.transition(VoiceEvent.MANUAL_READY)

    def process_utterance(self, frames: Sequence[AudioFrame]) -> VoiceTurnResult:
        """Process one bounded utterance without persisting PCM or bypassing Core."""

        if self.state is VoiceState.SLEEPING:
            return VoiceTurnResult(state=self.state)
        preroll = self.pre_roll.snapshot()
        turn_frames = (*preroll, *frames)
        if not turn_frames or not self.vad.contains_speech(turn_frames):
            if self.state is VoiceState.FOLLOW_UP_LISTENING:
                self.machine.transition(VoiceEvent.FOLLOW_UP_SILENCE)
                self.audio_buffer.clear()
                self.pre_roll.clear()
                self._reset_detector()
            else:
                self._sleep()
            return VoiceTurnResult(state=self.state)
        self.machine.transition(VoiceEvent.SPEECH_START)
        try:
            with self.audio_buffer.lifetime() as buffer:
                for frame in turn_frames:
                    buffer.append(frame)
                self.machine.transition(VoiceEvent.SPEECH_END)
                self.machine.transition(VoiceEvent.TRANSCRIPT_READY)
                transcript = strip_leading_wake_phrase(self.stt.transcribe(buffer.take()).strip())
        except Exception as exc:
            self.audio_buffer.clear()
            self.pre_roll.clear()
            self._reset_detector()
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
            client_message_id = str(uuid4())
            stream_method = getattr(self.core, "stream", None)
            if callable(stream_method):
                deltas = stream_method(transcript, client_message_id=client_message_id)
                if not deltas:
                    raise VoicePipelineError("Core returned no response events")
                response_text = "".join(delta.text for delta in deltas)
                request_id = deltas[0].request_id
                if not response_text:
                    raise VoicePipelineError("Core response events contained no text")
                response = CoreResponse(request_id=request_id, text=response_text)
            else:
                response = self.core.send(transcript, client_message_id=client_message_id)
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
                if self.tts_stream is not None:
                    audio_played = self.tts_stream.speak(response.text)
                else:
                    self.playback.play(self.tts.synthesize(response.text))
                    audio_played = True
            except Exception:
                # Text remains truthful and usable when local TTS/playback is unavailable.
                audio_played = False
        # A separate capture loop may have completed a barge-in while playback
        # was running.  Do not let the playback thread resurrect follow-up mode.
        if self.state is VoiceState.SPEAKING:
            self.pre_roll.clear()
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
        if self.tts_stream is not None:
            self.tts_stream.cancel()
        else:
            self.playback.stop()
        self.machine.transition(VoiceEvent.BARGE_IN)
        self.machine.transition(VoiceEvent.INTERRUPTION_READY)
        self.audio_buffer.clear()
        self.pre_roll.clear()
        self._reset_detector()
        return self.state

    def silence_timeout(self) -> VoiceState:
        """End the bounded follow-up window and return to wake-word-only idle."""

        if self.state is VoiceState.FOLLOW_UP_LISTENING:
            self.machine.transition(VoiceEvent.FOLLOW_UP_SILENCE)
            self.audio_buffer.clear()
            self.pre_roll.clear()
            self._reset_detector()
        return self.state

    def sleep(self) -> VoiceState:
        """Apply the local sleep command and stop active playback."""

        if self.state is VoiceState.SPEAKING:
            if self.tts_stream is not None:
                self.tts_stream.cancel()
            else:
                self.playback.stop()
        if self.state is not VoiceState.SLEEPING:
            self.machine.state = VoiceState.SLEEPING
        self.audio_buffer.clear()
        self.pre_roll.clear()
        self._reset_detector()
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
                    if self.tts_stream is not None:
                        self.tts_stream.speak(self._last_response)
                    else:
                        self.playback.play(self.tts.synthesize(self._last_response))
            self.machine.state = VoiceState.FOLLOW_UP_LISTENING
        return VoiceTurnResult(state=self.state, transcript=transcript, local_intent=intent)

    def _sleep(self) -> None:
        self.machine.state = VoiceState.SLEEPING
        self.audio_buffer.clear()
        self.pre_roll.clear()
        self._reset_detector()

    def turn_complete(self, frames: Sequence[AudioFrame], *, silence_seconds: float) -> bool:
        """Ask Smart Turn, with its bounded fallback, whether to submit a turn."""

        if self.turn_detector is None:
            return silence_seconds >= self.follow_up_timeout_seconds
        decision = self.turn_detector.decide(frames, silence_seconds=silence_seconds)
        return decision in {TurnDecision.COMPLETE, TurnDecision.FALLBACK_COMPLETE}

    def activate(self, source: ActivationSource) -> None:
        """Route all activation modes into the same state/session pipeline."""

        if source is ActivationSource.WAKE_WORD:
            raise VoicePipelineError("wake-word activation requires an audio frame")
        if source is ActivationSource.RIGHT_CTRL_DOUBLE_TAP:
            self.start_keyboard_capture()
        elif source is ActivationSource.PTT:
            self.start_manual_capture()


__all__ = ["JarvisVoicePipeline", "VoicePipelineError"]
