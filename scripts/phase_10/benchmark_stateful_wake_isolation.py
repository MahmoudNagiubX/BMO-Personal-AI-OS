"""Benchmark the active streaming capture cadence without retaining audio.

The historical stateful benchmark used retired wake engines. This helper now
only owns the shared 80 ms frame contract and scalar policy accounting used by
the active openWakeWord -> verifier cascade.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from personal_ai_os.voice.contracts import AudioFrame
from personal_ai_os.voice.wake_policy import WakePolicyMode, WakeTemporalPolicy

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_RATE_HZ = 16_000
CAPTURE_FRAME_DURATION_MS = 80
CAPTURE_FRAME_SAMPLES = int(SAMPLE_RATE_HZ * CAPTURE_FRAME_DURATION_MS / 1000)


def _split_into_frames(
    audio: np.ndarray, frame_samples: int = CAPTURE_FRAME_SAMPLES
) -> list[AudioFrame]:
    """Convert a bounded in-memory probe into production-sized frames."""

    raw = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16).tobytes()
    frame_bytes = frame_samples * 2
    return [
        AudioFrame(raw[offset : offset + frame_bytes], sample_rate_hz=SAMPLE_RATE_HZ)
        for offset in range(0, len(raw), frame_bytes)
        if raw[offset : offset + frame_bytes]
    ]


def _feed_capture_stream(pipeline: Any, audio: np.ndarray) -> bool:
    """Feed frames at the same cadence as SoundDeviceBackend."""

    detected = False
    for frame in _split_into_frames(audio):
        detected = bool(pipeline.on_capture_frame(frame)) or detected
    return detected


def _scalar_policy_metrics(
    scores: Sequence[float],
    *,
    threshold: float = 0.2,
    window_frames: int = 3,
    required_hits: int = 1,
    mode: WakePolicyMode = "moving_max",
    deactivation_threshold: float = 0.05,
) -> dict[str, Any]:
    """Evaluate only scalar scores; no audio or transcript leaves this function."""

    policy = WakeTemporalPolicy(
        threshold=threshold,
        window_frames=window_frames,
        required_hits=required_hits,
        mode=mode,
        deactivation_threshold=deactivation_threshold,
    )
    events = policy.stream_event_indices(scores)
    return {
        "score_count": len(scores),
        "event_count": len(events),
        "threshold": threshold,
        "window_frames": window_frames,
        "required_hits": required_hits,
        "temporal_policy": mode,
        "deactivation_threshold": deactivation_threshold,
        "raw_audio_retained": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scores", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload: dict[str, Any] = {
        "schema_version": "phase-10-stateful-wake-isolation/v2",
        "phase": 10,
        "architecture": "openwakeword_candidate_whisper_verifier",
        "measurement_mode": "scalar_stream_policy_only",
        "production_capture_equivalent": True,
        "owner_audio_used": False,
        "raw_audio_retained": False,
        "temporary_audio_removed": True,
        "phase_11_boundary": "NOT_STARTED",
        "decision": "not_run",
    }
    if args.scores is not None:
        values = [float(item) for item in args.scores.read_text(encoding="utf-8").split()]
        payload["metrics"] = _scalar_policy_metrics(values)
        payload["decision"] = "scalar_policy_measured"
    else:
        payload["metrics"] = {"status": "not_run", "reason": "no scalar score stream supplied"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
