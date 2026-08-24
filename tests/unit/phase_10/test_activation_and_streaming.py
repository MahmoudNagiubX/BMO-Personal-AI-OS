from __future__ import annotations

from collections.abc import Sequence

from personal_ai_os.voice.activation import ActivationRouter
from personal_ai_os.voice.contracts import ActivationSource, AudioFrame
from personal_ai_os.voice.streaming import CancellableTtsStream, VoicePresentationPolicy


def test_activation_router_uses_one_callback_for_all_sources() -> None:
    events: list[ActivationSource] = []
    router = ActivationRouter(events.append)
    router.wake_word()
    router.right_ctrl_double_tap()
    router.ptt()
    assert events == [
        ActivationSource.WAKE_WORD,
        ActivationSource.RIGHT_CTRL_DOUBLE_TAP,
        ActivationSource.PTT,
    ]


class FakeSynth:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def synthesize(self, text: str) -> Sequence[AudioFrame]:
        self.texts.append(text)
        return (AudioFrame(b"\x00\x00" * 8),)


class FakePlayback:
    def __init__(self) -> None:
        self.played = 0
        self.stopped = 0

    def play(self, frames: Sequence[AudioFrame]) -> None:
        self.played += 1

    def stop(self) -> None:
        self.stopped += 1


def test_tts_stream_preserves_all_safe_chunks_and_can_cancel() -> None:
    synth = FakeSynth()
    playback = FakePlayback()
    stream = CancellableTtsStream(
        synthesizer=synth,
        playback=playback,
        policy=VoicePresentationPolicy(max_chunk_characters=32),
        max_queue_chunks=1,
    )
    assert (
        stream.speak("First sentence is done. Second sentence is done. Third sentence is done.")
        is True
    )
    assert len(synth.texts) == 3
    assert playback.played == 3
    stream.cancel()
    assert playback.stopped == 1
