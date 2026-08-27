from __future__ import annotations

from collections.abc import Sequence

from personal_ai_os.voice.contracts import (
    ActivationSource,
    AudioFrame,
    CoreResponse,
    VoiceLocalIntent,
    VoiceState,
)
from personal_ai_os.voice.pipeline import JarvisVoicePipeline


class FakeWake:
    available = True

    def __init__(self) -> None:
        self.detected_calls = 0
        self.reset_calls = 0

    def detected(self, frame: AudioFrame) -> bool:
        self.detected_calls += 1
        return frame.pcm_s16le == b"wake"

    def reset(self) -> None:
        self.reset_calls += 1


class FakeVad:
    def __init__(self, speech: bool = True) -> None:
        self.speech = speech

    def contains_speech(self, frames: Sequence[AudioFrame]) -> bool:
        return self.speech


class FakeStt:
    def __init__(self, text: str = "hello") -> None:
        self.text = text
        self.calls = 0
        self.last_frames: Sequence[AudioFrame] = ()

    def transcribe(self, frames: Sequence[AudioFrame]) -> str:
        self.calls += 1
        self.last_frames = tuple(frames)
        return self.text


class FakeCore:
    def __init__(self, text: str = "response") -> None:
        self.text = text
        self.calls = 0

    def send(self, text: str, *, client_message_id: str) -> CoreResponse:
        self.calls += 1
        return CoreResponse(request_id="request-1", text=self.text)

    def available(self) -> bool:
        return True


class FakeTts:
    def synthesize(self, text: str) -> Sequence[AudioFrame]:
        return (AudioFrame(b"\x00\x00" * 16),)


class FakePlayback:
    def __init__(self) -> None:
        self.play_calls = 0
        self.stop_calls = 0

    def play(self, frames: Sequence[AudioFrame]) -> None:
        self.play_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1


def build(
    *, text: str = "hello", speech: bool = True
) -> tuple[JarvisVoicePipeline, FakeWake, FakeStt, FakeCore, FakePlayback]:
    wake = FakeWake()
    stt = FakeStt(text)
    core = FakeCore()
    playback = FakePlayback()
    pipeline = JarvisVoicePipeline(
        wake_word=wake,
        vad=FakeVad(speech),
        stt=stt,
        core=core,
        tts=FakeTts(),
        playback=playback,
        follow_up_timeout_seconds=2,
    )
    return pipeline, wake, stt, core, playback


def utterance() -> tuple[AudioFrame, ...]:
    return (AudioFrame(b"\x01\x00" * 160),)


def test_sleeping_wake_word_does_not_call_stt_or_core() -> None:
    pipeline, _, stt, core, _ = build()
    assert pipeline.on_wake_frame(AudioFrame(b"\x02\x00" * 16)) is False
    assert pipeline.process_utterance(utterance()).state is VoiceState.SLEEPING
    assert stt.calls == 0
    assert core.calls == 0
    assert pipeline.on_wake_frame(AudioFrame(b"wake")) is True


def test_successful_turn_enters_follow_up_without_repeated_wake() -> None:
    pipeline, _, stt, core, playback = build()
    pipeline.on_wake_frame(AudioFrame(b"wake"))
    result = pipeline.process_utterance(utterance())
    assert result.state is VoiceState.FOLLOW_UP_LISTENING
    assert result.response_text == "response"
    assert result.audio_played is True
    assert stt.calls == core.calls == playback.play_calls == 1
    follow_up = pipeline.process_utterance(utterance())
    assert follow_up.state is VoiceState.FOLLOW_UP_LISTENING
    assert core.calls == 2


def test_no_speech_makes_no_core_request_and_times_out() -> None:
    pipeline, _, stt, core, _ = build(speech=False)
    pipeline.on_wake_frame(AudioFrame(b"wake"))
    result = pipeline.process_utterance(utterance())
    assert result.state is VoiceState.SLEEPING
    assert stt.calls == core.calls == 0


def test_local_stop_does_not_call_core() -> None:
    pipeline, _, stt, core, _ = build(text="stop")
    pipeline.on_wake_frame(AudioFrame(b"wake"))
    result = pipeline.process_utterance(utterance())
    assert result.local_intent is VoiceLocalIntent.STOP
    assert result.state is VoiceState.SLEEPING
    assert stt.calls == 1
    assert core.calls == 0


def test_ptt_fallback_uses_the_same_pipeline() -> None:
    pipeline, _, _, core, _ = build()
    pipeline.start_manual_capture()
    result = pipeline.process_utterance(utterance())
    assert result.state is VoiceState.FOLLOW_UP_LISTENING
    assert core.calls == 1


def test_right_ctrl_activation_uses_the_same_pipeline() -> None:
    pipeline, _, _, core, _ = build()
    pipeline.activation_router.right_ctrl_double_tap()
    result = pipeline.process_utterance(utterance())
    assert result.state is VoiceState.FOLLOW_UP_LISTENING
    assert core.calls == 1
    assert ActivationSource.RIGHT_CTRL_DOUBLE_TAP.value == "right_ctrl_double_tap"


def test_core_failure_is_degraded_without_local_model_fallback() -> None:
    pipeline, _, _, core, _ = build()
    core.send = lambda text, client_message_id: (_ for _ in ()).throw(  # type: ignore[method-assign]
        ConnectionError("offline")
    )
    pipeline.on_wake_frame(AudioFrame(b"wake"))
    result = pipeline.process_utterance(utterance())
    assert result.state is VoiceState.DEGRADED
    assert result.response_text is None


def test_barge_in_is_idempotent_and_stops_only_voice_playback() -> None:
    pipeline, wake, _, _, playback = build()
    pipeline.machine.state = VoiceState.SPEAKING
    assert pipeline.barge_in() is VoiceState.LISTENING
    assert pipeline.barge_in() is VoiceState.LISTENING
    assert playback.stop_calls == 1
    assert wake.reset_calls >= 1
    assert pipeline.pre_roll.duration_seconds == 0.0


def test_tts_failure_keeps_text_response_available() -> None:
    pipeline, _, _, _, _ = build()
    pipeline.tts.synthesize = lambda text: (_ for _ in ()).throw(RuntimeError("tts down"))  # type: ignore[method-assign]
    pipeline.on_wake_frame(AudioFrame(b"wake"))
    result = pipeline.process_utterance(utterance())
    assert result.response_text == "response"
    assert result.audio_played is False
    assert result.state is VoiceState.FOLLOW_UP_LISTENING


def test_wake_inference_disarmed_outside_sleeping() -> None:
    pipeline, wake, _, _, _ = build()
    for state in (
        VoiceState.WAKE_DETECTED,
        VoiceState.LISTENING,
        VoiceState.SPEECH_DETECTED,
        VoiceState.TRANSCRIBING,
        VoiceState.SENDING,
        VoiceState.WAITING_FOR_RESPONSE,
        VoiceState.SPEAKING,
        VoiceState.FOLLOW_UP_LISTENING,
        VoiceState.INTERRUPTED,
        VoiceState.DEGRADED,
        VoiceState.FAILED,
    ):
        pipeline.machine.state = state
        wake_calls_before = wake.detected_calls
        assert pipeline.on_wake_frame(AudioFrame(b"wake")) is False
        assert pipeline.on_capture_frame(AudioFrame(b"wake")) is False
        assert wake.detected_calls == wake_calls_before
        assert pipeline.state is state


def test_assistant_self_playback_during_speaking_cannot_wake_or_contaminate_preroll() -> None:
    pipeline, wake, _, core, _ = build()
    pipeline.machine.state = VoiceState.SPEAKING
    tts_frames = [AudioFrame(b"wake") for _ in range(10)]
    for frame in tts_frames:
        assert pipeline.on_capture_frame(frame) is False
    assert wake.detected_calls == 0
    assert pipeline.pre_roll.duration_seconds == 0.0
    assert core.calls == 0


def test_assistant_self_playback_during_follow_up_cannot_wake() -> None:
    pipeline, wake, _, core, _ = build()
    pipeline.on_wake_frame(AudioFrame(b"wake"))
    result = pipeline.process_utterance(utterance())
    assert result.state is VoiceState.FOLLOW_UP_LISTENING
    assert core.calls == 1

    tts_frames = [AudioFrame(b"wake") for _ in range(10)]
    for frame in tts_frames:
        assert pipeline.on_capture_frame(frame) is False
    assert wake.detected_calls == 1  # only the initial wake

    follow_up_result = pipeline.process_utterance(utterance())
    assert follow_up_result.state is VoiceState.FOLLOW_UP_LISTENING
    assert core.calls == 2


def test_single_utterance_wake_plus_command_preserves_preroll() -> None:
    pipeline, _, stt, _, _ = build(text="Hey Jarvis open VS Code")
    wake_frame = AudioFrame(b"wake")
    command_frames = (AudioFrame(b"\x02\x00" * 80), AudioFrame(b"\x03\x00" * 80))
    detected = pipeline.on_capture_frame(wake_frame)
    assert detected is True
    assert pipeline.state is VoiceState.LISTENING

    result = pipeline.process_utterance(command_frames)
    assert result.state is VoiceState.FOLLOW_UP_LISTENING
    assert result.transcript == "open vs code"
    assert stt.calls == 1
    assert stt.last_frames == (wake_frame, *command_frames)


def test_silence_timeout_resets_detector_and_buffers() -> None:
    pipeline, wake, _, _, _ = build()
    pipeline.on_wake_frame(AudioFrame(b"wake"))
    pipeline.process_utterance(utterance())
    assert pipeline.state is VoiceState.FOLLOW_UP_LISTENING

    pipeline.silence_timeout()
    assert pipeline.state is VoiceState.SLEEPING
    assert wake.reset_calls >= 1
    assert pipeline.pre_roll.duration_seconds == 0.0


def test_immediate_sleep_during_speaking_cancels_playback_and_resets_detector() -> None:
    pipeline, wake, _, _, playback = build()
    pipeline.machine.state = VoiceState.SPEAKING
    pipeline.sleep()
    assert pipeline.state is VoiceState.SLEEPING
    assert playback.stop_calls == 1
    assert wake.reset_calls >= 1
    assert pipeline.pre_roll.duration_seconds == 0.0

    # Next clean wake activation functions normally
    assert pipeline.on_wake_frame(AudioFrame(b"wake")) is True
    assert pipeline.state is VoiceState.LISTENING
