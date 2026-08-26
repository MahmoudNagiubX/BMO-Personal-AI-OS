"""Bounded live JARVIS conversation coordination.

This module coordinates the already product-owned wake, VAD, STT, Core, and
TTS boundaries.  It owns no model, tool, approval, or business logic.  Audio
is retained only in bounded process memory and all public metrics are scalar.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

from personal_ai_os.voice.contracts import (
    ActivationSource,
    AudioFrame,
    TurnDecision,
    VoiceState,
    VoiceTurnResult,
)
from personal_ai_os.voice.pipeline import JarvisVoicePipeline
from personal_ai_os.voice.privacy import BoundedAudioBuffer
from personal_ai_os.voice.state import VoiceEvent


@dataclass(frozen=True, slots=True)
class ConversationMetrics:
    """Sanitized live-session counters and latency summaries."""

    core_submissions: int
    partial_submissions: int
    barge_in_count: int
    self_playback_barge_ins: int
    cancel_latency_p50_ms: float | None
    cancel_latency_p95_ms: float | None
    smart_turn_complete: int
    smart_turn_incomplete: int
    smart_turn_fallback_complete: int
    follow_up_turns: int
    failed_turns: int
    raw_audio_retained: bool

    def as_dict(self) -> dict[str, int | float | bool | None]:
        """Return scalar evidence without transcripts or audio."""

        return {
            "core_submissions": self.core_submissions,
            "partial_submissions": self.partial_submissions,
            "barge_in_count": self.barge_in_count,
            "self_playback_barge_ins": self.self_playback_barge_ins,
            "cancel_latency_p50_ms": self.cancel_latency_p50_ms,
            "cancel_latency_p95_ms": self.cancel_latency_p95_ms,
            "smart_turn_complete": self.smart_turn_complete,
            "smart_turn_incomplete": self.smart_turn_incomplete,
            "smart_turn_fallback_complete": self.smart_turn_fallback_complete,
            "follow_up_turns": self.follow_up_turns,
            "failed_turns": self.failed_turns,
            "raw_audio_retained": self.raw_audio_retained,
        }


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 3)


class JarvisConversationLoop:
    """Coordinate one bounded full-duplex conversation session.

    A single worker serializes final STT/Core/TTS turns.  Microphone frames
    continue to be accepted while TTS is speaking so a confirmed owner
    interruption can cancel the active presentation and preserve its first
    bounded frames.  No partial buffer is submitted to Core.
    """

    def __init__(
        self,
        pipeline: JarvisVoicePipeline,
        *,
        fallback_timeout_seconds: float = 2.5,
        barge_in_confirmation_seconds: float = 0.16,
        max_turn_seconds: float = 20.0,
        max_vad_window_seconds: float = 0.64,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if fallback_timeout_seconds <= 0:
            raise ValueError("full-duplex fallback timeout must be positive")
        if not 0.12 <= barge_in_confirmation_seconds <= 0.24:
            raise ValueError("barge-in confirmation must be between 120 and 240 ms")
        if max_turn_seconds <= 0 or max_vad_window_seconds <= 0:
            raise ValueError("conversation audio bounds must be positive")
        self.pipeline = pipeline
        self.fallback_timeout_seconds = fallback_timeout_seconds
        self.barge_in_confirmation_seconds = barge_in_confirmation_seconds
        self.max_turn_seconds = max_turn_seconds
        self.max_vad_window_seconds = max_vad_window_seconds
        self._clock = clock
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bmo-voice-turn")
        self._turn_buffer = BoundedAudioBuffer(max_seconds=max_turn_seconds)
        self._vad_frames: deque[AudioFrame] = deque()
        self._barge_frames: deque[AudioFrame] = deque()
        self._barge_speech_seconds = 0.0
        self._barge_started_at: float | None = None
        self._speech_started_at: float | None = None
        self._last_speech_at: float | None = None
        self._follow_up_started_at: float | None = None
        self._logical_time = 0.0
        self._turn_ready = False
        self._turn_in_flight = False
        self._turn_future: Future[VoiceTurnResult] | None = None
        self._idle = threading.Event()
        self._idle.set()
        self._closed = False
        self._last_result: VoiceTurnResult | None = None
        self._cancel_latencies: list[float] = []
        self._core_submissions = 0
        self._partial_submissions = 0
        self._barge_in_count = 0
        self._self_playback_barge_ins = 0
        self._smart_turn_complete = 0
        self._smart_turn_incomplete = 0
        self._smart_turn_fallback_complete = 0
        self._follow_up_turns = 0
        self._failed_turns = 0

    @property
    def state(self) -> VoiceState:
        """Return the current product-owned state."""

        return self.pipeline.state

    @property
    def state_history(self) -> tuple[VoiceState, ...]:
        """Return only the scalar state sequence for diagnostics/tests."""

        with self._lock:
            return tuple(self.pipeline.machine.history)

    @property
    def last_result(self) -> VoiceTurnResult | None:
        """Return the latest typed result; callers must not persist transcripts."""

        with self._lock:
            return self._last_result

    @property
    def metrics(self) -> ConversationMetrics:
        """Return sanitized scalar metrics for the current session."""

        with self._lock:
            latencies = tuple(self._cancel_latencies)
            return ConversationMetrics(
                core_submissions=self._core_submissions,
                partial_submissions=self._partial_submissions,
                barge_in_count=self._barge_in_count,
                self_playback_barge_ins=self._self_playback_barge_ins,
                cancel_latency_p50_ms=_percentile(latencies, 0.50),
                cancel_latency_p95_ms=_percentile(latencies, 0.95),
                smart_turn_complete=self._smart_turn_complete,
                smart_turn_incomplete=self._smart_turn_incomplete,
                smart_turn_fallback_complete=self._smart_turn_fallback_complete,
                follow_up_turns=self._follow_up_turns,
                failed_turns=self._failed_turns,
                raw_audio_retained=False,
            )

    def activate(self, source: ActivationSource) -> VoiceState:
        """Enter the same pipeline for keyboard or PTT activation."""

        with self._lock:
            self._ensure_open()
            self.pipeline.activate(source)
            self._reset_turn_state()
            self._follow_up_started_at = self._logical_time
            return self.pipeline.state

    def on_frame(self, frame: AudioFrame) -> VoiceState:
        """Consume one microphone frame according to the current state."""

        with self._lock:
            self._ensure_open()
            self._logical_time += frame.duration_seconds
            state = self.pipeline.state
            if state is VoiceState.SLEEPING:
                if self.pipeline.on_capture_frame(frame):
                    wake_frames = self.pipeline.pre_roll.snapshot()
                    self._reset_turn_state()
                    for wake_frame in wake_frames:
                        self._turn_buffer.append(wake_frame)
                    self._follow_up_started_at = None
                return self.pipeline.state
            if state is VoiceState.SPEAKING:
                self._observe_speaking(frame)
                return self.pipeline.state
            if state in {
                VoiceState.LISTENING,
                VoiceState.FOLLOW_UP_LISTENING,
                VoiceState.SPEECH_DETECTED,
            }:
                self._observe_owner_turn(frame)
            return self.pipeline.state

    def feed(self, frames: Sequence[AudioFrame]) -> VoiceState:
        """Consume a bounded sequence of microphone frames."""

        for frame in frames:
            self.on_frame(frame)
        return self.state

    def silence_timeout(self) -> VoiceState:
        """Apply the bounded follow-up timeout and clear process-memory audio."""

        with self._lock:
            self.pipeline.silence_timeout()
            self._reset_turn_state()
            return self.pipeline.state

    def wait_for_idle(self, timeout_seconds: float = 5.0) -> bool:
        """Wait for the single bounded turn worker without spinning forever."""

        if timeout_seconds <= 0:
            raise ValueError("wait timeout must be positive")
        return self._idle.wait(timeout_seconds)

    def close(self) -> None:
        """Stop local playback, clear audio, and shut down the bounded worker."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            self.pipeline.sleep()
            self._reset_turn_state()
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _observe_owner_turn(self, frame: AudioFrame) -> None:
        state = self.pipeline.state
        speech_present = self._speech_present(frame)
        if state in {VoiceState.LISTENING, VoiceState.FOLLOW_UP_LISTENING}:
            if speech_present:
                self._append_turn_frame(frame)
                self._speech_started_at = self._logical_time - frame.duration_seconds
                self._last_speech_at = self._logical_time
                self.pipeline.machine.transition(VoiceEvent.SPEECH_START)
                self._follow_up_started_at = None
            elif state is VoiceState.FOLLOW_UP_LISTENING:
                if self._follow_up_started_at is None:
                    self._follow_up_started_at = self._logical_time
                if (
                    self._logical_time - self._follow_up_started_at
                    >= self.pipeline.follow_up_timeout_seconds
                ):
                    self.pipeline.silence_timeout()
                    self._reset_turn_state()
            return

        self._append_turn_frame(frame)
        if speech_present:
            if self._speech_started_at is None:
                self._speech_started_at = self._logical_time - frame.duration_seconds
            self._last_speech_at = self._logical_time
            return
        if self._last_speech_at is None:
            return
        silence_seconds = self._logical_time - self._last_speech_at
        if self._turn_complete(silence_seconds):
            self._turn_ready = True
            self._submit_if_possible()

    def _observe_speaking(self, frame: AudioFrame) -> None:
        self._append_bounded(self._barge_frames, frame, self.max_vad_window_seconds / 2)
        speech_present = self._speech_present(frame, speaking=True)
        if not speech_present:
            self._barge_speech_seconds = 0.0
            self._barge_started_at = None
            return
        if self._barge_started_at is None:
            self._barge_started_at = self._clock()
        self._barge_speech_seconds += frame.duration_seconds
        if self._barge_speech_seconds < self.barge_in_confirmation_seconds:
            return
        started = self._barge_started_at
        preserved = tuple(self._barge_frames)
        self.pipeline.barge_in()
        latency_ms = (self._clock() - started) * 1000.0 if started is not None else 0.0
        self._cancel_latencies.append(latency_ms)
        self._barge_in_count += 1
        self._reset_turn_state()
        for preserved_frame in preserved:
            self._append_turn_frame(preserved_frame)
        self._barge_frames.clear()
        self._speech_started_at = self._logical_time - sum(
            item.duration_seconds for item in preserved
        )
        self._last_speech_at = self._logical_time
        self.pipeline.machine.transition(VoiceEvent.SPEECH_START)

    def _speech_present(self, frame: AudioFrame, *, speaking: bool = False) -> bool:
        window = self._vad_frames if not speaking else self._barge_frames
        if not speaking:
            self._append_bounded(window, frame, self.max_vad_window_seconds)
        try:
            # Evaluate the newest frame so earlier speech cannot mask a real
            # silence boundary; history remains bounded for endpointing.
            return bool(self.pipeline.vad.contains_speech((frame,)))
        except Exception:
            self._failed_turns += 1
            return False

    def _turn_complete(self, silence_seconds: float) -> bool:
        detector = self.pipeline.turn_detector
        if detector is None:
            decision = (
                TurnDecision.FALLBACK_COMPLETE
                if silence_seconds >= self.fallback_timeout_seconds
                else TurnDecision.INCOMPLETE
            )
        else:
            try:
                decision = detector.decide(
                    tuple(self._turn_buffer_snapshot()), silence_seconds=silence_seconds
                )
            except Exception:
                self._failed_turns += 1
                decision = (
                    TurnDecision.FALLBACK_COMPLETE
                    if silence_seconds >= self.fallback_timeout_seconds
                    else TurnDecision.INCOMPLETE
                )
        if decision is TurnDecision.COMPLETE:
            self._smart_turn_complete += 1
        elif decision is TurnDecision.FALLBACK_COMPLETE:
            self._smart_turn_fallback_complete += 1
        else:
            self._smart_turn_incomplete += 1
        return decision in {TurnDecision.COMPLETE, TurnDecision.FALLBACK_COMPLETE}

    def _submit_if_possible(self) -> None:
        if not self._turn_ready or self._turn_in_flight:
            return
        if self.pipeline.state is not VoiceState.SPEECH_DETECTED:
            self._turn_ready = False
            return
        frames = self._turn_buffer.take()
        if not frames:
            self._turn_ready = False
            return
        self._turn_ready = False
        self._turn_in_flight = True
        self._idle.clear()
        future = self._executor.submit(self._run_turn, frames)
        self._turn_future = future
        future.add_done_callback(self._finish_turn)

    def _run_turn(self, frames: Sequence[AudioFrame]) -> VoiceTurnResult:
        """Run one final turn; all model and tool authority stays in the pipeline."""

        return self.pipeline.process_utterance(frames)

    def _finish_turn(self, future: Future[VoiceTurnResult]) -> None:
        try:
            result = future.result()
        except Exception:
            with self._lock:
                self._failed_turns += 1
                self._turn_in_flight = False
                self._turn_future = None
                if self.pipeline.state not in {VoiceState.SLEEPING, VoiceState.DEGRADED}:
                    self.pipeline.machine.degrade()
                self._clear_if_idle()
            return
        with self._lock:
            self._last_result = result
            self._turn_in_flight = False
            self._turn_future = None
            if result.core_request_id is not None:
                self._core_submissions += 1
            if result.degraded_reason is not None:
                self._failed_turns += 1
            if result.state is VoiceState.FOLLOW_UP_LISTENING:
                self._follow_up_turns += 1
                self._follow_up_started_at = self._logical_time
            elif result.state is VoiceState.SLEEPING:
                self._reset_turn_state()
            if self._turn_ready:
                self._submit_if_possible()
            self._clear_if_idle()

    def _clear_if_idle(self) -> None:
        if not self._turn_in_flight:
            self._idle.set()

    def _append_turn_frame(self, frame: AudioFrame) -> None:
        self._turn_buffer.append(frame)

    def _turn_buffer_snapshot(self) -> tuple[AudioFrame, ...]:
        return self._turn_buffer.snapshot()

    def _reset_turn_state(self) -> None:
        self._turn_buffer.clear()
        self._vad_frames.clear()
        self._barge_frames.clear()
        self._barge_speech_seconds = 0.0
        self._barge_started_at = None
        self._speech_started_at = None
        self._last_speech_at = None
        self._turn_ready = False

    def _append_bounded(
        self, frames: deque[AudioFrame], frame: AudioFrame, max_seconds: float
    ) -> None:
        frames.append(frame)
        while len(frames) > 1 and sum(item.duration_seconds for item in frames) > max_seconds:
            frames.popleft()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("conversation loop is closed")


__all__ = ["ConversationMetrics", "JarvisConversationLoop"]
