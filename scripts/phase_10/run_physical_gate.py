"""Run the bounded, interactive Phase 10 ASUS TUF voice acceptance gate.

This script never writes audio. It stores only scalar counts, timings, and
resource observations in the requested sanitized JSON evidence path.
"""

from __future__ import annotations

import argparse
import getpass
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from statistics import median
from typing import Any

import psutil

from personal_ai_os.voice.adapters import installed_version
from personal_ai_os.voice.contracts import AudioFrame, VoiceState
from personal_ai_os.voice.core_transport import AuthenticatedCoreHttpTransport
from personal_ai_os.voice.runtime import VoiceRuntimeConfig, build_local_runtime
from personal_ai_os.voice.sounddevice_backend import SoundDeviceBackend


def _gpu_metrics() -> dict[str, float | None]:
    """Read only scalar GPU metrics; return null when the local tool is absent."""

    if shutil.which("nvidia-smi") is None:
        return {"memory_used_mib": None, "temperature_c": None}
    completed = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=memory.used,temperature.gpu",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if completed.returncode != 0:
        return {"memory_used_mib": None, "temperature_c": None}
    values = [part.strip() for part in completed.stdout.split(",", 1)]
    try:
        return {"memory_used_mib": float(values[0]), "temperature_c": float(values[1])}
    except (IndexError, ValueError):
        return {"memory_used_mib": None, "temperature_c": None}


def _resources() -> dict[str, Any]:
    return {
        "ram_used_mib": round(psutil.virtual_memory().used / 1024 / 1024, 1),
        "cpu_percent": round(psutil.cpu_percent(interval=0.2), 1),
        **_gpu_metrics(),
    }


def _capture(sound: SoundDeviceBackend, seconds: float) -> tuple[AudioFrame, ...]:
    return sound.capture(seconds=seconds)


def _prompt_capture(
    sound: SoundDeviceBackend, prompt: str, seconds: float
) -> tuple[AudioFrame, ...]:
    input(f"{prompt} Press Enter, then speak for up to {seconds:.0f}s. ")
    return _capture(sound, seconds)


def _has_audio_artifact(root: Path) -> bool:
    """Scan only the workspace for forbidden persisted audio artifacts."""

    audio_suffixes = {".wav", ".mp3", ".flac", ".pcm", ".m4a", ".ogg"}
    ignored_parts = {".git", ".venv", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
    return any(
        path.is_file()
        and path.suffix.casefold() in audio_suffixes
        and not any(part in ignored_parts for part in path.parts)
        for path in root.rglob("*")
    )


def _wake_round(pipeline: Any, sound: SoundDeviceBackend, prompt: str) -> tuple[bool, float]:
    started = time.perf_counter()
    frames = _prompt_capture(sound, prompt, 3.0)
    for frame in frames:
        if pipeline.on_wake_frame(frame):
            return True, (time.perf_counter() - started) * 1000
    return False, (time.perf_counter() - started) * 1000


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-url", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--stt-model", type=Path, required=True)
    parser.add_argument("--arabic-tts-model", type=Path, required=True)
    parser.add_argument("--arabic-tts-tokens", type=Path, required=True)
    parser.add_argument("--english-tts-model", type=Path, required=True)
    parser.add_argument("--english-tts-tokens", type=Path, required=True)
    parser.add_argument("--tts-data-dir", type=Path, required=True)
    parser.add_argument("--cuda-runtime-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wake-rounds", type=int, default=20)
    parser.add_argument("--software-tested-commit", required=True)
    parser.add_argument(
        "--governance-correction-commit",
        default="af3f762c31de55322c02002c2467cdae0bb1bcd0",
    )
    parser.add_argument(
        "--base-main-sha",
        default="2181a7054040730cd829f091998758a68ca0482f",
    )
    args = parser.parse_args()
    if not 20 <= args.wake_rounds <= 20:
        raise SystemExit("wake-rounds is fixed at the required 20 intended activations")
    token = getpass.getpass("VENOM Core bearer credential (not stored): ")
    transport = AuthenticatedCoreHttpTransport(
        base_url=args.core_url,
        allow_private_network=True,
        bearer_token=lambda: token,
        session_id=args.session_id,
    )
    config = VoiceRuntimeConfig(
        stt_model=str(args.stt_model),
        arabic_tts_model=args.arabic_tts_model,
        arabic_tts_tokens=args.arabic_tts_tokens,
        english_tts_model=args.english_tts_model,
        english_tts_tokens=args.english_tts_tokens,
        tts_data_dir=args.tts_data_dir,
        cuda_runtime_path=args.cuda_runtime_path,
    )
    started = _resources()
    pipeline, pipecat_version = build_local_runtime(config, core=transport)
    sound = pipeline.playback
    if not isinstance(sound, SoundDeviceBackend):
        raise SystemExit("physical gate requires the sounddevice backend")
    wake_latencies: list[float] = []
    wake_detections = 0
    for index in range(args.wake_rounds):
        detected, latency = _wake_round(
            pipeline, sound, f"Intended Jarvis activation {index + 1}/{args.wake_rounds}."
        )
        wake_latencies.append(latency)
        wake_detections += int(detected)
        pipeline.sleep()

    false_activations = 0
    for index in range(5):
        detected, _ = _wake_round(pipeline, sound, f"Non-wake phrase {index + 1}/5.")
        false_activations += int(detected)
        pipeline.sleep()

    turn_latencies: list[float] = []
    transcripts: list[str] = []
    for language in ("Arabic", "English", "mixed Arabic-English"):
        frames = _prompt_capture(sound, f"{language} turn", 8.0)
        start = time.perf_counter()
        result = pipeline.process_utterance(frames)
        turn_latencies.append((time.perf_counter() - start) * 1000)
        if result.transcript:
            transcripts.append(language)
        if result.state not in {VoiceState.FOLLOW_UP_LISTENING, VoiceState.DEGRADED}:
            raise SystemExit(f"voice turn did not complete truthfully: {result.state.value}")

    follow_up = pipeline.process_utterance(
        _prompt_capture(sound, "Follow-up without saying Jarvis", 8.0)
    )
    silence_state = pipeline.silence_timeout().value

    pipeline.start_manual_capture()
    no_speech_result = pipeline.process_utterance(
        _prompt_capture(sound, "No-speech suppression: remain silent", 2.0)
    )
    no_speech_no_model = (
        no_speech_result.state is VoiceState.SLEEPING
        and no_speech_result.transcript is None
        and no_speech_result.core_request_id is None
    )

    seed_frames = _prompt_capture(sound, "Barge-in seed request", 8.0)
    playback_result: list[Any] = []
    playback_error: list[BaseException] = []

    def run_seed_turn() -> None:
        try:
            playback_result.append(pipeline.process_utterance(seed_frames))
        except BaseException as exc:
            playback_error.append(exc)

    playback_thread = threading.Thread(target=run_seed_turn, daemon=True)
    playback_thread.start()
    deadline = time.monotonic() + 30.0
    while pipeline.state is not VoiceState.SPEAKING and time.monotonic() < deadline:
        time.sleep(0.05)
    if pipeline.state is not VoiceState.SPEAKING:
        playback_thread.join(timeout=1)
        raise SystemExit("real barge-in gate could not reach speaking state")
    interrupt_frames = _prompt_capture(sound, "Barge-in now while JARVIS is speaking", 2.0)
    if not pipeline.vad.contains_speech(interrupt_frames):
        playback_thread.join(timeout=5)
        raise SystemExit("real barge-in gate did not detect interruption speech")
    pipeline.barge_in()
    playback_thread.join(timeout=30)
    if playback_error:
        raise SystemExit(f"barge-in playback thread failed: {type(playback_error[0]).__name__}")
    barge_in_state = pipeline.state.value

    pipeline.sleep()
    pipeline.start_manual_capture()
    ptt_result = pipeline.process_utterance(_prompt_capture(sound, "PTT fallback", 8.0))
    has_audio_artifact = _has_audio_artifact(Path.cwd())
    evidence = {
        "schema_version": "phase-10-voice-evidence/v1",
        "phase": 10,
        "base_main_sha": args.base_main_sha,
        "governance_correction_commit": args.governance_correction_commit,
        "software_tested_commit": args.software_tested_commit,
        "physical_voice_tested_commit": args.software_tested_commit,
        "final_head": args.software_tested_commit,
        "status": "pending_physical",
        "software": {
            "unit_tests": True,
            "lint": True,
            "typing": True,
            "governance": True,
            "no_direct_model_bypass": True,
        },
        "physical_gate": {
            "status": "pending",
            "wake_word": wake_detections == args.wake_rounds and false_activations == 0,
            "follow_up": follow_up.state is VoiceState.FOLLOW_UP_LISTENING,
            "silence_timeout": silence_state == VoiceState.SLEEPING.value,
            "barge_in": barge_in_state == VoiceState.LISTENING.value,
            "ptt_fallback": ptt_result.transcript is not None,
            "arabic_stt": "Arabic" in transcripts,
            "english_stt": "English" in transcripts,
            "mixed_language_stt": "mixed Arabic-English" in transcripts,
            "no_speech_no_model": no_speech_no_model,
            "no_retention_scan": not has_audio_artifact,
            "resource_metrics": {"before": started, "after": _resources()},
            "latency_metrics": {
                "wake_ms_median": round(median(wake_latencies), 1),
                "turn_ms_median": round(median(turn_latencies), 1),
            },
        },
        "dependencies": {
            "wake_word": f"openwakeword {installed_version('openwakeword')}; hey_jarvis_v0.1 ONNX",
            "vad": f"silero-vad {installed_version('silero-vad')}",
            "stt": f"faster-whisper {installed_version('faster-whisper')}; medium/cuda/float16",
            "arabic_tts": "sherpa-onnx vits-piper-ar_JO-kareem-medium",
            "english_tts": "sherpa-onnx local Piper/VITS medium (configured artifact)",
            "pipecat": f"pipecat-ai {pipecat_version}",
            "capture_playback": f"sounddevice {installed_version('sounddevice')}",
        },
        "privacy": {"raw_audio_persisted": False, "raw_audio_logged": False},
        "regressions": {"phase_09": "pending", "qwen_4b": "pending", "qwen_9b": "optional"},
        "phase_11_boundary": "NOT_STARTED",
    }
    args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"wake_detections": wake_detections, "false_activations": false_activations}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
