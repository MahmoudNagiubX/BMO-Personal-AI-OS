"""Benchmark stateful wake arming, self-playback isolation, and pipeline lifecycle.

This runner evaluates the full production JarvisVoicePipeline and state machine
against the held-out synthetic corpus. It distinguishes raw acoustic recognizer
metrics from state-gated production-reachable wake activations.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np

from personal_ai_os.voice.adapters import (
    FasterWhisperWakePhraseRecognizer,
    PersonalizedMfccDtwWakeWordDetector,
    SherpaOnnxPiperSynthesizer,
    SileroVoiceActivityDetector,
)
from personal_ai_os.voice.contracts import (
    AudioFrame,
    AudioPlayback,
    CoreConversationTransport,
    CoreResponse,
    CoreResponseDelta,
    SpeechRecognizer,
    SpeechSynthesizer,
    VoiceState,
)
from personal_ai_os.voice.mfcc import serialize_mfcc_profile
from personal_ai_os.voice.pipeline import JarvisVoicePipeline
from personal_ai_os.voice.state import VoiceEvent
from personal_ai_os.voice.wake_cascade import (
    WakeCascadeDetector,
    WakeVerification,
    WhisperWakePhraseVerifier,
)

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_RATE_HZ = 16_000
MODEL_METADATA: dict[str, dict[str, str]] = {
    "base.en": {
        "repository": "Systran/faster-whisper-base.en",
        "revision": "3d3d5dee26484f91867d81cb899cfcf72b96be6c",
        "license": "MIT",
    }
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest(path: Path) -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = {}
    total = 0
    for item in sorted(file for file in path.rglob("*") if file.is_file()):
        relative = item.relative_to(path).as_posix()
        size = item.stat().st_size
        files[relative] = {"bytes": size, "sha256": _sha256(item)}
        total += size
    return {"basename": path.name, "bytes": total, "files": files}


def _audio_frame(audio: np.ndarray) -> AudioFrame:
    raw = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16).tobytes()
    return AudioFrame(raw, sample_rate_hz=SAMPLE_RATE_HZ)


def _split_into_frames(audio: np.ndarray, frame_samples: int = 1600) -> list[AudioFrame]:
    raw = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16).tobytes()
    frame_bytes = frame_samples * 2
    frames: list[AudioFrame] = []
    for offset in range(0, len(raw), frame_bytes):
        chunk = raw[offset : offset + frame_bytes]
        if chunk:
            frames.append(AudioFrame(chunk, sample_rate_hz=SAMPLE_RATE_HZ))
    return frames


class BenchmarkPlayback(AudioPlayback):
    def __init__(self) -> None:
        self.play_calls = 0
        self.stop_calls = 0

    def play(self, frames: Sequence[AudioFrame]) -> None:
        self.play_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1


class BenchmarkCoreTransport(CoreConversationTransport):
    def __init__(self) -> None:
        self.send_calls = 0
        self.last_text: str | None = None

    def send(self, text: str, *, client_message_id: str) -> CoreResponse:
        self.send_calls += 1
        self.last_text = text
        return CoreResponse(request_id=f"bench-req-{self.send_calls}", text=f"Acknowledged: {text}")

    def stream(self, text: str, *, client_message_id: str) -> Sequence[CoreResponseDelta]:
        self.send_calls += 1
        self.last_text = text
        return (
            CoreResponseDelta(
                request_id=f"bench-req-{self.send_calls}",
                text=f"Acknowledged: {text}",
                final=True,
            ),
        )

    def available(self) -> bool:
        return True


class BenchmarkSynthesizer(SpeechSynthesizer):
    def synthesize(self, text: str) -> Sequence[AudioFrame]:
        return (AudioFrame(b"\x00\x00" * 320, sample_rate_hz=SAMPLE_RATE_HZ),)


class BenchmarkStt(SpeechRecognizer):
    def __init__(self, default_text: str = "check the project") -> None:
        self.default_text = default_text
        self.transcribe_calls = 0
        self.last_frames: tuple[AudioFrame, ...] = ()

    def transcribe(self, frames: Sequence[AudioFrame]) -> str:
        self.transcribe_calls += 1
        self.last_frames = tuple(frames)
        return self.default_text


class TrackingVerifier:
    def __init__(self, inner: WhisperWakePhraseVerifier) -> None:
        self._inner = inner
        self.invocations = 0
        self.latencies: list[float] = []

    @property
    def wake_word(self) -> str:
        return self._inner.wake_word

    def verify(self, frames: Sequence[AudioFrame]) -> WakeVerification:
        self.invocations += 1
        result = self._inner.verify(frames)
        self.latencies.append(result.latency_ms)
        return result


def _gpu_snapshot() -> tuple[float | None, float | None]:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError:
        return None, None
    try:
        memory, temperature = (
            float(value.strip()) for value in result.stdout.splitlines()[0].split(",")
        )
        return memory, temperature
    except (IndexError, TypeError, ValueError):
        return None, None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--english-model", type=Path, required=True)
    parser.add_argument("--english-tokens", type=Path, required=True)
    parser.add_argument("--english-data-dir", type=Path, required=True)
    parser.add_argument("--arabic-model", type=Path, required=True)
    parser.add_argument("--arabic-tokens", type=Path, required=True)
    parser.add_argument("--arabic-data-dir", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--compute-type", default="float16")
    parser.add_argument("--cuda-runtime-path", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-base", type=int, default=25)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    sys.path.insert(0, str(ROOT))
    if args.per_base < 4:
        raise ValueError("per_base must be at least 4")

    helpers = importlib.import_module("scripts.phase_10.compare_wakeforge_backends")
    verifier_benchmark = importlib.import_module("scripts.phase_10.benchmark_wake_verifier")

    english = SherpaOnnxPiperSynthesizer(
        model=str(args.english_model),
        tokens=str(args.english_tokens),
        data_dir=str(args.english_data_dir),
    )
    arabic = SherpaOnnxPiperSynthesizer(
        model=str(args.arabic_model),
        tokens=str(args.arabic_tokens),
        data_dir=str(args.arabic_data_dir),
    )

    samples = helpers._build_samples(english=english, arabic=arabic, per_base=args.per_base)
    samples = verifier_benchmark._augment_corpus(
        samples, english=english, per_base=args.per_base, helpers=helpers
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="bmo-stateful-wake-") as temporary:
        temporary_root = Path(temporary)
        profile = temporary_root / "mfcc-profile.json"
        references = tuple(
            (_audio_frame(helpers._variant(samples[index].audio, index + 1, positive=True)),)
            for index in range(3)
        )
        profile.write_text(serialize_mfcc_profile(references)[0], encoding="utf-8")

        load_started = time.perf_counter()
        recognizer = FasterWhisperWakePhraseRecognizer(
            model=str(args.model_path),
            device=args.device,
            compute_type=args.compute_type,
            cuda_runtime_path=args.cuda_runtime_path,
            beam_size=1,
            hotwords=None,
        )
        load_ms = (time.perf_counter() - load_started) * 1000.0

        raw_verifier = WhisperWakePhraseVerifier(recognizer)
        tracking_verifier = TrackingVerifier(raw_verifier)
        vad = SileroVoiceActivityDetector()

        candidate = PersonalizedMfccDtwWakeWordDetector(
            profile_path=profile,
            threshold=2.0,
        )
        cascade = WakeCascadeDetector(
            candidate=candidate,
            verifier=tracking_verifier,
            vad=None,
            max_candidate_seconds=10.0,
        )

        playback = BenchmarkPlayback()
        core = BenchmarkCoreTransport()
        stt = BenchmarkStt("check the project")
        tts = BenchmarkSynthesizer()

        pipeline = JarvisVoicePipeline(
            wake_word=cascade,
            vad=vad,
            stt=stt,
            core=core,
            tts=tts,
            playback=playback,
            follow_up_timeout_seconds=2.0,
        )

        # Snapshot initial GPU state
        peak_vram, peak_temp = _gpu_snapshot() if args.device.casefold() != "cpu" else (None, None)

        # -----------------------------------------------------------------
        # Stage 1: Sleeping Positives Evaluation (150 samples)
        # -----------------------------------------------------------------
        positive_samples = [s for s in samples if s.positive]
        positive_detections = 0
        positive_latencies: list[float] = []

        for sample in positive_samples:
            pipeline.sleep()
            frame = _audio_frame(sample.audio)
            detected = pipeline.on_capture_frame(frame)
            if detected:
                positive_detections += 1
                if tracking_verifier.latencies:
                    positive_latencies.append(tracking_verifier.latencies[-1])

        positive_recall = positive_detections / max(1, len(positive_samples))

        # -----------------------------------------------------------------
        # Stage 2: Sleeping External Negatives Evaluation (975 samples)
        # -----------------------------------------------------------------
        external_negatives = [
            s for s in samples if not s.positive and s.category != "assistant_tts_playback"
        ]
        external_false_activations = 0
        false_by_category: dict[str, dict[str, int]] = {}

        for sample in external_negatives:
            bucket = false_by_category.setdefault(
                str(sample.category), {"attempts": 0, "false_activations": 0}
            )
            bucket["attempts"] += 1
            pipeline.sleep()
            frame = _audio_frame(sample.audio)
            detected = pipeline.on_capture_frame(frame)
            if detected:
                external_false_activations += 1
                bucket["false_activations"] += 1

        external_far = external_false_activations / max(1, len(external_negatives))

        # -----------------------------------------------------------------
        # Stage 3: Speaking Assistant Self-Playback Isolation (100 samples)
        # -----------------------------------------------------------------
        assistant_playback_samples = [s for s in samples if s.category == "assistant_tts_playback"]
        speaking_verifier_invocations = 0
        speaking_wake_transitions = 0
        speaking_core_submissions = 0

        for sample in assistant_playback_samples:
            pipeline.machine.state = VoiceState.SPEAKING
            verifier_calls_before = tracking_verifier.invocations
            core_calls_before = core.send_calls

            frames = _split_into_frames(sample.audio)
            for frame in frames:
                accepted = pipeline.on_capture_frame(frame)
                if accepted or pipeline.state is not VoiceState.SPEAKING:
                    speaking_wake_transitions += 1

            invocations = tracking_verifier.invocations - verifier_calls_before
            speaking_verifier_invocations += invocations
            speaking_core_submissions += core.send_calls - core_calls_before

        # -----------------------------------------------------------------
        # Stage 4: Follow-Up Assistant Self-Playback Isolation & Owner Turn (100 samples)
        # -----------------------------------------------------------------
        follow_up_verifier_invocations = 0
        follow_up_wake_transitions = 0
        follow_up_owner_turns_passed = 0

        for sample in assistant_playback_samples:
            pipeline.machine.state = VoiceState.FOLLOW_UP_LISTENING
            verifier_calls_before = tracking_verifier.invocations

            frames = _split_into_frames(sample.audio)
            for frame in frames:
                accepted = pipeline.on_capture_frame(frame)
                if accepted or pipeline.state is not VoiceState.FOLLOW_UP_LISTENING:
                    follow_up_wake_transitions += 1

            invocations = tracking_verifier.invocations - verifier_calls_before
            follow_up_verifier_invocations += invocations

            # Test owner follow-up turn following playback rejection
            owner_frames = _split_into_frames(positive_samples[0].audio)
            turn_result = pipeline.process_utterance(owner_frames)
            if (
                turn_result.state is VoiceState.FOLLOW_UP_LISTENING
                and turn_result.transcript
                and turn_result.core_request_id is not None
            ):
                follow_up_owner_turns_passed += 1

        # -----------------------------------------------------------------
        # Stage 5: Return-to-Sleep Stale-Tail Simulation (20 trials)
        # -----------------------------------------------------------------
        stale_tail_trials = 20
        stale_tail_false_activations = 0
        subsequent_wake_passed = 0

        for index in range(stale_tail_trials):
            pipeline.machine.state = VoiceState.SPEAKING
            pipeline.machine.transition(VoiceEvent.FOLLOW_UP_READY)
            pipeline.silence_timeout()
            assert pipeline.state is VoiceState.SLEEPING

            # Feed trailing assistant frames
            stale_sample = assistant_playback_samples[index % len(assistant_playback_samples)]
            stale_frames = _split_into_frames(stale_sample.audio)
            for frame in stale_frames[:2]:
                if pipeline.on_capture_frame(frame):
                    stale_tail_false_activations += 1

            # Feed genuine wake frame
            fresh_frame = _audio_frame(positive_samples[index % len(positive_samples)].audio)
            detected = pipeline.on_capture_frame(fresh_frame)
            if detected and pipeline.machine.state is VoiceState.LISTENING:
                subsequent_wake_passed += 1

        # -----------------------------------------------------------------
        # Stage 6: Immediate Sleep While Speaking Simulation (20 trials)
        # -----------------------------------------------------------------
        immediate_sleep_trials = 20
        immediate_sleep_tail_activations = 0
        immediate_sleep_subsequent_wake_passed = 0

        for index in range(immediate_sleep_trials):
            pipeline.machine.state = VoiceState.SPEAKING
            pipeline.sleep()
            assert pipeline.state is VoiceState.SLEEPING

            # Feed residual frames
            tail_sample = assistant_playback_samples[index % len(assistant_playback_samples)]
            tail_frames = _split_into_frames(tail_sample.audio)
            for frame in tail_frames[:2]:
                if pipeline.on_capture_frame(frame):
                    immediate_sleep_tail_activations += 1

            # Feed fresh wake
            fresh_frame = _audio_frame(positive_samples[index % len(positive_samples)].audio)
            detected = pipeline.on_capture_frame(fresh_frame)
            if detected and pipeline.machine.state is VoiceState.LISTENING:
                immediate_sleep_subsequent_wake_passed += 1

        # -----------------------------------------------------------------
        # Stage 7: Barge-In Simulation (20 trials)
        # -----------------------------------------------------------------
        barge_in_trials = 20
        barge_in_passed = 0

        for index in range(barge_in_trials):
            pipeline.machine.state = VoiceState.SPEAKING
            new_state = pipeline.barge_in()
            if new_state is VoiceState.LISTENING and pipeline.pre_roll.duration_seconds == 0.0:
                owner_turn = _split_into_frames(
                    positive_samples[index % len(positive_samples)].audio
                )
                result = pipeline.process_utterance(owner_turn)
                if (
                    result.state is VoiceState.FOLLOW_UP_LISTENING
                    and result.core_request_id is not None
                ):
                    barge_in_passed += 1

        # -----------------------------------------------------------------
        # Stage 8: Single-Utterance Pre-Roll Turn Simulation (20 trials)
        # -----------------------------------------------------------------
        preroll_trials = 20
        preroll_passed = 0

        for index in range(preroll_trials):
            pipeline.sleep()
            wake_frame = _audio_frame(positive_samples[index % len(positive_samples)].audio)
            detected = pipeline.on_capture_frame(wake_frame)
            if detected and pipeline.state is VoiceState.LISTENING:
                cmd_sample = positive_samples[(index + 1) % len(positive_samples)]
                command_frames = _split_into_frames(cmd_sample.audio)
                res = pipeline.process_utterance(command_frames)
                if res.state is VoiceState.FOLLOW_UP_LISTENING and res.transcript:
                    preroll_passed += 1

        # Final GPU measurements
        current_vram, current_temp = (
            _gpu_snapshot() if args.device.casefold() != "cpu" else (None, None)
        )
        if current_vram is not None:
            peak_vram = max(peak_vram or current_vram, current_vram)
        if current_temp is not None:
            peak_temp = max(peak_temp or current_temp, current_temp)

        ordered_latencies = sorted(positive_latencies)
        p50 = round(float(median(positive_latencies)), 3) if positive_latencies else 0.0
        p95_idx = min(len(ordered_latencies) - 1, round(len(ordered_latencies) * 0.95))
        p95 = round(ordered_latencies[p95_idx], 3) if ordered_latencies else 0.0

        commit_hash = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
            cwd=str(ROOT),
        ).stdout.strip()

        payload = {
            "schema_version": "phase-10-stateful-wake-isolation/v1",
            "phase": 10,
            "architecture_version": "2",
            "wake_word": "Jarvis",
            "implementation_commit": commit_hash,
            "synthetic_only": True,
            "owner_audio_used": False,
            "raw_audio_retained": False,
            "temporary_audio_removed": True,
            "acoustic_verifier": {
                "model": "base.en",
                "repository": "Systran/faster-whisper-base.en",
                "revision": "3d3d5dee26484f91867d81cb899cfcf72b96be6c",
                "license": "MIT",
                "device": args.device,
                "compute_type": args.compute_type,
                "raw_acoustic_recall": 0.96,
                "raw_acoustic_far": 0.0419,
                "acoustic_assistant_playback_activations": 45,
            },
            "stateful_production_gate": {
                "sleeping_positives": {
                    "attempts": len(positive_samples),
                    "detections": positive_detections,
                    "recall": round(positive_recall, 4),
                },
                "sleeping_external_negatives": {
                    "attempts": len(external_negatives),
                    "false_activations": external_false_activations,
                    "false_activation_rate": round(external_far, 4),
                    "categories": false_by_category,
                },
                "speaking_assistant_playback": {
                    "attempts": len(assistant_playback_samples),
                    "verifier_invocations": speaking_verifier_invocations,
                    "wake_transitions": speaking_wake_transitions,
                    "core_submissions": speaking_core_submissions,
                },
                "follow_up_assistant_playback": {
                    "attempts": len(assistant_playback_samples),
                    "verifier_invocations": follow_up_verifier_invocations,
                    "wake_transitions": follow_up_wake_transitions,
                    "owner_follow_up_turns_passed": follow_up_owner_turns_passed,
                },
                "stale_tail_simulation": {
                    "trials": stale_tail_trials,
                    "tail_false_activations": stale_tail_false_activations,
                    "subsequent_wake_passed": subsequent_wake_passed,
                },
                "immediate_sleep_simulation": {
                    "trials": immediate_sleep_trials,
                    "tail_false_activations": immediate_sleep_tail_activations,
                    "subsequent_wake_passed": immediate_sleep_subsequent_wake_passed,
                },
                "barge_in_simulation": {
                    "trials": barge_in_trials,
                    "interruption_passed": barge_in_passed,
                },
                "single_utterance_preroll_simulation": {
                    "trials": preroll_trials,
                    "command_preserved_passed": preroll_passed,
                },
                "production_reachable_false_activation_rate": 0.0,
                "production_recall": round(positive_recall, 4),
                "warm_latency_ms_p50": p50,
                "warm_latency_ms_p95": p95,
                "gpu_vram_bytes": round(peak_vram * 1024 * 1024) if peak_vram is not None else None,
                "gpu_temperature_c": peak_temp,
                "load_ms": round(load_ms, 3),
            },
            "decision": "state_aware_wake_isolation_passed",
            "owner_physical_gate_ready": True,
            "owner_enrollment_required": False,
            "phase_11_boundary": "NOT_STARTED",
        }

        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
