"""Verify the BMO adapter against the minimal pyopen-wakeword reference loop."""

from __future__ import annotations

import importlib
from typing import Any

from personal_ai_os.voice.contracts import AudioFrame
from personal_ai_os.voice.rhasspy_wake import (
    DEFAULT_REFRACTORY_SECONDS,
    DEFAULT_THRESHOLD,
    DEFAULT_TRIGGER_LEVEL,
    RhasspyHeyJarvisDetector,
    split_pcm16_chunks,
)

FRAME_BYTES = 2_560


def _reference_probabilities(pcm_s16le: bytes) -> tuple[list[float], int | None]:
    module: Any = importlib.import_module("pyopen_wakeword")
    features: Any = module.OpenWakeWordFeatures.from_builtin()
    wake: Any = module.OpenWakeWord.from_builtin(module.Model.HEY_JARVIS)
    probabilities: list[float] = []
    trigger_frame: int | None = None
    try:
        for frame_index, offset in enumerate(range(0, len(pcm_s16le), FRAME_BYTES)):
            frame = pcm_s16le[offset : offset + FRAME_BYTES]
            chunks, residual = split_pcm16_chunks(frame)
            if residual:
                raise ValueError("parity stream must contain complete 10 ms chunks")
            frame_probabilities: list[float] = []
            for chunk in chunks:
                for embedding in features.process_streaming(chunk):
                    frame_probabilities.extend(
                        float(value) for value in wake.process_streaming(embedding)
                    )
            probabilities.extend(frame_probabilities)
            if trigger_frame is None and any(
                value > DEFAULT_THRESHOLD for value in frame_probabilities
            ):
                trigger_frame = frame_index
    finally:
        features.close()
        wake.close()
    return probabilities, trigger_frame


def main() -> int:
    # Deterministic in-memory input; this is a stream-shape parity check, not
    # an acoustic quality claim.
    pcm = bytes((index * 37) % 256 for index in range(16_000 * 2 * 10))
    reference, reference_trigger_frame = _reference_probabilities(pcm)
    observed: list[float] = []
    detector = RhasspyHeyJarvisDetector(
        threshold=DEFAULT_THRESHOLD,
        trigger_level=DEFAULT_TRIGGER_LEVEL,
        refractory_seconds=DEFAULT_REFRACTORY_SECONDS,
        clock=lambda: 0.0,
        probability_observer=observed.append,
    )
    adapter_trigger_frames: list[int] = []
    try:
        for frame_index, offset in enumerate(range(0, len(pcm), FRAME_BYTES)):
            if detector.detected(AudioFrame(pcm[offset : offset + FRAME_BYTES])):
                adapter_trigger_frames.append(frame_index)
    finally:
        detector.close()
    adapter_detected = bool(adapter_trigger_frames)
    reference_detected = reference_trigger_frame is not None
    adapter_trigger_frame = adapter_trigger_frames[0] if adapter_trigger_frames else None
    if len(observed) != len(reference) or any(
        abs(actual - expected) > 1e-6 for actual, expected in zip(observed, reference, strict=True)
    ):
        raise RuntimeError("BMO/reference probability sequence mismatch")
    if adapter_detected != reference_detected:
        raise RuntimeError("BMO/reference detection decision mismatch")
    if adapter_trigger_frame != reference_trigger_frame:
        raise RuntimeError("BMO/reference trigger frame mismatch")
    print(
        "RHASSPY_PARITY_PASS "
        f"probabilities={len(reference)} "
        f"detected={adapter_detected} "
        f"same_sequence=true same_decision=true trigger_frame={adapter_trigger_frame} "
        "same_trigger_frame=true raw_audio_retained=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
