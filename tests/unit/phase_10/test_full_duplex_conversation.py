from __future__ import annotations

import threading
from collections.abc import Callable, Sequence

import pytest

from personal_ai_os.voice.contracts import (
    ActivationSource,
    AudioFrame,
    CoreResponseDelta,
    TurnDecision,
    VoiceState,
)
from personal_ai_os.voice.conversation_loop import JarvisConversationLoop
from personal_ai_os.voice.pipeline import JarvisVoicePipeline

FRAME_BYTES = b"\x01\x00" * 1280
SILENCE_BYTES = b"\x00\x00" * 1280
WAKE_BYTES = b"\x02\x00" * 1280


def speech_frame() -> AudioFrame:
    return AudioFrame(FRAME_BYTES)


def silence_frame() -> AudioFrame:
    return AudioFrame(SILENCE_BYTES)


class FakeWake:
    available = True

    def __init__(self) -> None:
        self.calls = 0

    def detected(self, frame: AudioFrame) -> bool:
        self.calls += 1
        return frame.pcm_s16le == WAKE_BYTES

    def reset(self) -> None:
        return None


class EnergyVad:
    def contains_speech(self, frames: Sequence[AudioFrame]) -> bool:
        return any(frame.pcm_s16le != SILENCE_BYTES for frame in frames)


class QueueStt:
    def __init__(self, texts: Sequence[str]) -> None:
        self.texts = list(texts)
        self.calls = 0
        self.frames: list[tuple[AudioFrame, ...]] = []

    def transcribe(self, frames: Sequence[AudioFrame]) -> str:
        self.calls += 1
        self.frames.append(tuple(frames))
        text = self.texts.pop(0)
        if text == "__ERROR__":
            raise RuntimeError("synthetic STT failure")
        return text


class FakeCore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def send(self, text: str, *, client_message_id: str):
        self.calls.append((text, client_message_id))
        return type("Response", (), {"request_id": f"request-{len(self.calls)}", "text": "ack"})()


class StreamingCore(FakeCore):
    def stream(self, text: str, *, client_message_id: str) -> Sequence[CoreResponseDelta]:
        self.calls.append((text, client_message_id))
        request_id = f"request-{len(self.calls)}"
        return (
            CoreResponseDelta(request_id=request_id, text=f"ack {len(self.calls)}", final=True),
        )


class FakeTts:
    def synthesize(self, text: str) -> Sequence[AudioFrame]:
        return (speech_frame(),)


class Playback:
    def __init__(self, *, block_first: bool = False) -> None:
        self.play_calls = 0
        self.stop_calls = 0
        self.started = threading.Event()
        self.release = threading.Event()
        self.block_first = block_first

    def play(self, frames: Sequence[AudioFrame]) -> None:
        self.play_calls += 1
        self.started.set()
        if self.block_first and self.play_calls == 1:
            self.release.wait(timeout=2.0)

    def stop(self) -> None:
        self.stop_calls += 1
        self.release.set()


class ThresholdTurn:
    def __init__(self, complete_after: float = 0.16) -> None:
        self.complete_after = complete_after
        self.decisions: list[TurnDecision] = []

    def decide(self, frames: Sequence[AudioFrame], *, silence_seconds: float) -> TurnDecision:
        decision = (
            TurnDecision.COMPLETE
            if silence_seconds >= self.complete_after
            else TurnDecision.INCOMPLETE
        )
        self.decisions.append(decision)
        return decision


def build(
    *,
    texts: Sequence[str] = ("check project", "wait", "follow up"),
    core: FakeCore | StreamingCore | None = None,
    playback: Playback | None = None,
    turn: ThresholdTurn | None = None,
    playback_echo_detector: Callable[[AudioFrame], bool] | None = None,
) -> tuple[JarvisConversationLoop, FakeWake, QueueStt, FakeCore | StreamingCore, Playback]:
    wake = FakeWake()
    stt = QueueStt(texts)
    selected_core = core or FakeCore()
    selected_playback = playback or Playback()
    pipeline = JarvisVoicePipeline(
        wake_word=wake,
        vad=EnergyVad(),
        stt=stt,
        core=selected_core,
        tts=FakeTts(),
        playback=selected_playback,
        turn_detector=turn or ThresholdTurn(),
    )
    return (
        JarvisConversationLoop(
            pipeline,
            playback_echo_detector=playback_echo_detector,
        ),
        wake,
        stt,
        selected_core,
        selected_playback,
    )


def complete_turn(
    loop: JarvisConversationLoop, *, silence_frames: int = 3, wait: bool = True
) -> None:
    loop.on_frame(speech_frame())
    loop.feed((silence_frame(),) * silence_frames)
    if wait:
        assert loop.wait_for_idle(2.0)


def test_normal_turn_has_one_final_submission_and_follow_up() -> None:
    loop, wake, stt, core, playback = build()
    try:
        assert loop.activate(ActivationSource.RIGHT_CTRL_DOUBLE_TAP) is VoiceState.LISTENING
        complete_turn(loop)
        assert loop.state is VoiceState.FOLLOW_UP_LISTENING
        assert stt.calls == len(core.calls) == playback.play_calls == 1
        assert wake.calls == 0
    finally:
        loop.close()


def test_incomplete_pause_does_not_submit_until_continuation() -> None:
    turn = ThresholdTurn(complete_after=1.0)
    loop, _, stt, core, _ = build(turn=turn)
    try:
        loop.activate(ActivationSource.PTT)
        loop.on_frame(speech_frame())
        loop.feed((silence_frame(),) * 10)
        assert core.calls == []
        loop.on_frame(speech_frame())
        loop.feed((silence_frame(),) * 13)
        assert loop.wait_for_idle(2.0)
        assert stt.calls == 1
        assert len(core.calls) == 1
    finally:
        loop.close()


def test_hesitation_is_not_submitted_as_partial_speech() -> None:
    turn = ThresholdTurn(complete_after=1.0)
    loop, _, _, core, _ = build(turn=turn)
    try:
        loop.activate(ActivationSource.PTT)
        loop.on_frame(speech_frame())
        loop.feed((silence_frame(),) * 8)
        assert core.calls == []
    finally:
        loop.close()


def test_self_correction_is_submitted_once_as_complete_text() -> None:
    loop, _, stt, core, _ = build(texts=("open Chrome no I mean VS Code",))
    try:
        loop.activate(ActivationSource.PTT)
        complete_turn(loop)
        assert stt.calls == 1
        assert len(core.calls) == 1
        assert core.calls[0][0] == "open Chrome no I mean VS Code"
    finally:
        loop.close()


def test_barge_in_cancels_playback_and_preserves_interruption_frames() -> None:
    playback = Playback(block_first=True)
    loop, _, stt, core, _ = build(texts=("status", "only backend"), playback=playback)
    try:
        loop.activate(ActivationSource.PTT)
        complete_turn(loop, wait=False)
        assert playback.started.wait(1.0)
        loop.feed((speech_frame(), speech_frame()))
        assert loop.state is VoiceState.SPEECH_DETECTED
        playback.release.set()
        loop.feed((silence_frame(),) * 10)
        assert loop.wait_for_idle(2.0)
        assert playback.stop_calls == 1
        assert len(core.calls) == 2
        assert stt.frames[1]
        assert loop.metrics.barge_in_count == 1
        assert loop.metrics.cancel_latency_p95_ms is not None
    finally:
        loop.close()


def test_contextual_interruption_uses_same_core_session_without_wake() -> None:
    playback = Playback(block_first=True)
    loop, wake, _, core, _ = build(texts=("tests", "only backend"), playback=playback)
    try:
        loop.activate(ActivationSource.PTT)
        complete_turn(loop, wait=False)
        assert playback.started.wait(1.0)
        loop.feed((speech_frame(), speech_frame()))
        playback.release.set()
        loop.feed((silence_frame(),) * 10)
        assert loop.wait_for_idle(2.0)
        assert len(core.calls) == 2
        assert wake.calls == 0
    finally:
        loop.close()


def test_follow_up_works_without_wake_and_timeout_returns_to_sleep() -> None:
    loop, wake, _, core, _ = build(texts=("status", "do it"))
    try:
        loop.activate(ActivationSource.PTT)
        complete_turn(loop)
        complete_turn(loop)
        assert len(core.calls) == 2
        assert wake.calls == 0
        loop.feed((silence_frame(),) * 101)
        assert loop.state is VoiceState.SLEEPING
    finally:
        loop.close()


def test_self_playback_alone_does_not_barge_in() -> None:
    playback = Playback(block_first=True)
    loop, _, _, _, _ = build(playback=playback)
    try:
        loop.activate(ActivationSource.PTT)
        complete_turn(loop, wait=False)
        assert playback.started.wait(1.0)
        loop.feed((silence_frame(),) * 5)
        assert loop.state is VoiceState.SPEAKING
        assert loop.metrics.barge_in_count == 0
        playback.release.set()
        assert loop.wait_for_idle(2.0)
    finally:
        loop.close()


def test_playback_only_leakage_is_ignored_by_the_playback_aware_guard() -> None:
    playback = Playback(block_first=True)
    loop, _, _, _, _ = build(
        playback=playback,
        playback_echo_detector=lambda frame: frame.pcm_s16le == FRAME_BYTES,
    )
    try:
        loop.activate(ActivationSource.PTT)
        complete_turn(loop, wait=False)
        assert playback.started.wait(1.0)
        loop.feed((speech_frame(), speech_frame(), speech_frame()))
        assert loop.state is VoiceState.SPEAKING
        assert loop.metrics.barge_in_count == 0
        assert loop.metrics.playback_echo_frames_ignored == 3
        playback.release.set()
        assert loop.wait_for_idle(2.0)
    finally:
        loop.close()


def test_stt_failure_after_barge_in_is_safe_and_old_response_does_not_resume() -> None:
    playback = Playback(block_first=True)
    loop, _, stt, core, _ = build(texts=("first", "__ERROR__"), playback=playback)
    try:
        loop.activate(ActivationSource.PTT)
        complete_turn(loop, wait=False)
        assert playback.started.wait(1.0)
        loop.feed((speech_frame(), speech_frame()))
        playback.release.set()
        loop.feed((silence_frame(),) * 3)
        assert loop.wait_for_idle(2.0)
        assert stt.calls == 2
        assert len(core.calls) == 1
        assert loop.state is VoiceState.FAILED
        assert loop.metrics.failed_turns >= 1
    finally:
        loop.close()


def test_mixed_language_turn_remains_one_authenticated_submission() -> None:
    loop, _, stt, core, _ = build(texts=("Check the project لا استنى backend بس",))
    try:
        loop.activate(ActivationSource.PTT)
        complete_turn(loop, wait=False)
        assert stt.calls == 1
        assert len(core.calls) == 1
        assert "backend" in core.calls[0][0]
    finally:
        loop.close()


def test_wake_activation_preserves_pre_roll_and_does_not_call_wake_after_activation() -> None:
    loop, wake, stt, core, _ = build(texts=("check project",))
    try:
        assert loop.on_frame(AudioFrame(WAKE_BYTES)) is VoiceState.LISTENING
        wake_calls = wake.calls
        complete_turn(loop)
        assert wake.calls == wake_calls
        assert stt.calls == len(core.calls) == 1
    finally:
        loop.close()


def test_state_history_records_normal_and_interrupted_sequences() -> None:
    playback = Playback(block_first=True)
    loop, _, _, _, _ = build(playback=playback)
    try:
        loop.activate(ActivationSource.PTT)
        complete_turn(loop, wait=False)
        assert playback.started.wait(1.0)
        loop.feed((speech_frame(), speech_frame()))
        playback.release.set()
        expected = (
            VoiceState.LISTENING,
            VoiceState.SPEECH_DETECTED,
            VoiceState.TRANSCRIBING,
            VoiceState.SENDING,
            VoiceState.WAITING_FOR_RESPONSE,
            VoiceState.SPEAKING,
            VoiceState.INTERRUPTED,
            VoiceState.LISTENING,
            VoiceState.SPEECH_DETECTED,
        )
        history = loop.state_history
        positions: list[int] = []
        cursor = 0
        for state in expected:
            position = history.index(state, cursor)
            positions.append(position)
            cursor = position + 1
        assert positions == sorted(positions)
    finally:
        loop.close()


def test_end_to_end_synthetic_full_duplex_lifecycle_is_exactly_once() -> None:
    playback = Playback(block_first=True)
    core = StreamingCore()
    loop, _, stt, selected_core, _ = build(
        texts=("check project and", "only backend", "do it"),
        core=core,
        playback=playback,
        turn=ThresholdTurn(complete_after=0.8),
    )
    try:
        loop.activate(ActivationSource.RIGHT_CTRL_DOUBLE_TAP)
        loop.on_frame(speech_frame())
        loop.feed((silence_frame(),) * 5)
        assert core.calls == []
        loop.on_frame(speech_frame())
        loop.feed((silence_frame(),) * 10)
        assert playback.started.wait(1.0)

        loop.feed((speech_frame(), speech_frame()))
        playback.release.set()
        loop.feed((silence_frame(),) * 10)
        assert loop.wait_for_idle(2.0)

        complete_turn(loop, silence_frames=10)
        assert loop.state is VoiceState.FOLLOW_UP_LISTENING
        loop.silence_timeout()

        assert stt.calls == 3
        assert len(selected_core.calls) == 3
        assert loop.metrics.raw_audio_retained is False
        assert loop.state is VoiceState.SLEEPING
    finally:
        loop.close()


def test_closed_loop_rejects_new_frames() -> None:
    loop, _, _, _, _ = build()
    loop.close()
    with pytest.raises(RuntimeError, match="closed"):
        loop.on_frame(speech_frame())
