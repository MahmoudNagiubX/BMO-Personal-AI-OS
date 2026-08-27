from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from personal_ai_os.voice.contracts import AudioFrame
from personal_ai_os.voice.rhasspy_wake import (
    BYTES_PER_WAKE_CHUNK,
    RhasspyHeyJarvisDetector,
    split_pcm16_chunks,
)


class _FakeFeatures:
    def __init__(self) -> None:
        self.chunks: list[bytes] = []
        self.reset_calls = 0

    def process_streaming(self, audio_chunk: bytes) -> tuple[object, ...]:
        self.chunks.append(audio_chunk)
        return (object(),)

    def reset(self) -> None:
        self.reset_calls += 1


class _FakeWake:
    def __init__(self, scores: list[float]) -> None:
        self.scores = iter(scores)
        self.calls = 0
        self.reset_calls = 0

    def process_streaming(self, _embedding: object) -> tuple[float, ...]:
        self.calls += 1
        return (next(self.scores),)

    def reset(self) -> None:
        self.reset_calls += 1


def _install_fake_runtime(
    monkeypatch: pytest.MonkeyPatch, scores: list[float]
) -> tuple[_FakeFeatures, _FakeWake]:
    features = _FakeFeatures()
    wake = _FakeWake(scores)
    module = SimpleNamespace(
        Model=SimpleNamespace(HEY_JARVIS=object()),
        OpenWakeWordFeatures=SimpleNamespace(from_builtin=lambda: features),
        OpenWakeWord=SimpleNamespace(from_builtin=lambda _model: wake),
    )
    monkeypatch.setattr(
        "personal_ai_os.voice.rhasspy_wake.importlib.import_module",
        lambda name: module if name == "pyopen_wakeword" else None,
    )
    return features, wake


def test_80ms_frame_splits_into_eight_10ms_chunks() -> None:
    pcm = bytes(value % 256 for value in range(2560))
    chunks, residual = split_pcm16_chunks(pcm)
    assert len(chunks) == 8
    assert all(len(chunk) == BYTES_PER_WAKE_CHUNK for chunk in chunks)
    assert b"".join(chunks) + residual == pcm


def test_arbitrary_residual_chunking_conserves_every_byte(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parts = (b"a" * 318, b"b" * 322, b"c" * 18, b"d" * 640)
    features, _ = _install_fake_runtime(monkeypatch, [0.1] * 5)
    detector = RhasspyHeyJarvisDetector()
    for part in parts:
        detector.detected(AudioFrame(part))
    assert b"".join(features.chunks) + detector.residual_bytes == b"".join(parts)


def test_streaming_state_persists_across_bmo_frames_and_matches_reference_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    features, wake = _install_fake_runtime(monkeypatch, [0.1, 0.2, 0.1, 0.2])
    detector = RhasspyHeyJarvisDetector()
    first = bytes(range(256)) * 2 + bytes(range(128))
    second = bytes(reversed(range(256))) * 2 + bytes(reversed(range(128)))
    assert detector.detected(AudioFrame(first)) is False
    assert detector.detected(AudioFrame(second)) is False
    assert features.chunks == [first[:320], first[320:], second[:320], second[320:]]
    assert wake.calls == 4


def test_default_threshold_trigger_and_refractory_are_rhasspy_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [10.0]
    _install_fake_runtime(monkeypatch, [0.5001, 0.9, 0.9])
    detector = RhasspyHeyJarvisDetector(clock=lambda: now[0])
    frame = AudioFrame(b"\x01\x00" * 160)
    assert detector.threshold == 0.5
    assert detector.trigger_level == 1
    assert detector.refractory_seconds == 2.0
    assert detector.detected(frame) is True
    assert detector.detected(frame) is False
    now[0] = 12.1
    assert detector.detected(frame) is True


def test_refractory_continues_advancing_features(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [0.0]
    features, wake = _install_fake_runtime(monkeypatch, [0.9, 0.9, 0.1])
    detector = RhasspyHeyJarvisDetector(clock=lambda: now[0])
    frame = AudioFrame(b"\x01\x00" * 160)
    assert detector.detected(frame) is True
    assert detector.detected(frame) is False
    assert len(features.chunks) == 2
    assert wake.calls == 2


def test_reset_clears_upstream_and_detector_state(monkeypatch: pytest.MonkeyPatch) -> None:
    features, wake = _install_fake_runtime(monkeypatch, [0.9])
    detector = RhasspyHeyJarvisDetector()
    detector.detected(AudioFrame(b"\x01\x00" * 160 + b"xx"))
    detector.reset()
    assert features.reset_calls == wake.reset_calls == 1
    assert detector.residual_bytes == b""
    assert detector.last_probability == 0.0
    assert detector.available is True


def test_missing_dependency_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(_name: str) -> Any:
        raise ImportError("not installed")

    monkeypatch.setattr("personal_ai_os.voice.rhasspy_wake.importlib.import_module", missing)
    with pytest.raises(RuntimeError, match="pyopen-wakeword"):
        RhasspyHeyJarvisDetector()


def test_noncanonical_audio_is_rejected_before_model_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_runtime(monkeypatch, [0.9])
    detector = RhasspyHeyJarvisDetector()
    with pytest.raises(ValueError, match="16 kHz mono"):
        detector.detected(AudioFrame(b"\x01\x00" * 160, sample_rate_hz=8_000))
