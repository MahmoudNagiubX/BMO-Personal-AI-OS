"""Run the bounded, interactive Phase 10 ASUS TUF voice acceptance gate.

The runner keeps microphone PCM in memory only. It records scalar counts,
timings, resource peaks, statuses, versions, and hashes in sanitized JSON.
Stage A is a hard gate: no Core credential is requested and no speech/model
request is attempted until bare ``Jarvis`` is practically usable.
"""

from __future__ import annotations

import argparse
import array
import getpass
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any, NoReturn, cast

import psutil

from personal_ai_os.voice.adapters import installed_version
from personal_ai_os.voice.contracts import AudioFrame, CoreResponse, VoiceState
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


@dataclass
class ResourceMonitor:
    """Sample only scalar local resources while the bounded session runs."""

    interval_seconds: float = 1.0
    samples: list[dict[str, Any]] = field(default_factory=list)
    _stop: threading.Event = field(default_factory=threading.Event, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)

    def start(self) -> None:
        self.samples.append(_resources())
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self.samples.append(_resources())

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self.samples.append(_resources())
        numeric = {
            key: [
                value for value in (sample.get(key) for sample in self.samples) if value is not None
            ]
            for key in ("cpu_percent", "ram_used_mib", "memory_used_mib", "temperature_c")
        }
        return {
            "before": self.samples[0] if self.samples else {},
            "after": self.samples[-1] if self.samples else {},
            "peak_cpu_percent": round(max(numeric["cpu_percent"], default=0.0), 1),
            "peak_ram_used_mib": round(max(numeric["ram_used_mib"], default=0.0), 1),
            "peak_gpu_memory_used_mib": round(max(numeric["memory_used_mib"], default=0.0), 1)
            if numeric["memory_used_mib"]
            else None,
            "peak_gpu_temperature_c": round(max(numeric["temperature_c"], default=0.0), 1)
            if numeric["temperature_c"]
            else None,
            "sample_count": len(self.samples),
        }


class TimedSpeechRecognizer:
    """Measure STT duration without retaining the transcript or PCM."""

    def __init__(self, wrapped: Any) -> None:
        self._wrapped = wrapped
        self.durations_ms: list[float] = []

    def transcribe(self, frames: Any) -> str:
        started = time.perf_counter()
        try:
            return str(self._wrapped.transcribe(frames))
        finally:
            self.durations_ms.append((time.perf_counter() - started) * 1000)


class TimedCoreTransport:
    """Measure authenticated Core requests while preserving the transport boundary."""

    def __init__(self, wrapped: Any) -> None:
        self._wrapped = wrapped
        self.durations_ms: list[float] = []

    def available(self) -> bool:
        return bool(self._wrapped.available())

    def send(self, text: str, *, client_message_id: str) -> CoreResponse:
        started = time.perf_counter()
        try:
            return cast(CoreResponse, self._wrapped.send(text, client_message_id=client_message_id))
        finally:
            self.durations_ms.append((time.perf_counter() - started) * 1000)


class TimedSynthesizer:
    """Measure first local TTS audio availability without storing audio."""

    def __init__(self, wrapped: Any) -> None:
        self._wrapped = wrapped
        self.durations_ms: list[float] = []

    def synthesize(self, text: str) -> Any:
        started = time.perf_counter()
        try:
            return self._wrapped.synthesize(text)
        finally:
            self.durations_ms.append((time.perf_counter() - started) * 1000)


class UnavailableCore:
    """Bounded local fault injector used only for the degraded-mode proof."""

    def available(self) -> bool:
        return False

    def send(self, _text: str, *, client_message_id: str) -> CoreResponse:
        del client_message_id
        raise RuntimeError("bounded_core_unavailable_probe")


class UnavailableTts:
    """Bounded local fault injector used only for text-preserving TTS proof."""

    def synthesize(self, _text: str) -> NoReturn:
        raise RuntimeError("bounded_tts_unavailable_probe")


class NoMicrophoneAudio(RuntimeError):
    """The device opened but no owner speech was observed after bounded retries."""


class OwnerPhysicalAbort(RuntimeError):
    """The owner interrupted the local physical session."""


def _capture(sound: SoundDeviceBackend, seconds: float) -> tuple[AudioFrame, ...]:
    return sound.capture(seconds=seconds)


def _audio_level(frames: tuple[AudioFrame, ...]) -> dict[str, float]:
    """Return scalar RMS/peak levels and immediately discard PCM callers."""

    samples = array.array("h", b"".join(frame.pcm_s16le for frame in frames))
    if not samples:
        return {"rms": 0.0, "peak": 0.0}
    peak = max(abs(sample) for sample in samples) / 32768.0
    rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768.0
    return {"rms": round(rms, 6), "peak": round(peak, 6)}


def _countdown(prompt: str) -> None:
    print(f"\n{prompt}")
    for remaining in (3, 2, 1):
        print(f"  {remaining}...", flush=True)
        time.sleep(1)


def _prompt_capture(
    sound: SoundDeviceBackend,
    prompt: str,
    seconds: float,
    *,
    expect_audio: bool = True,
    retries: int = 2,
) -> tuple[AudioFrame, ...]:
    for attempt in range(retries + 1):
        _countdown(f"{prompt} Speak naturally after the countdown.")
        frames = _capture(sound, seconds)
        level = _audio_level(frames)
        if not expect_audio or level["peak"] >= 0.003:
            return frames
        if attempt < retries:
            print("  No microphone audio detected; retrying this prompt.", flush=True)
    raise NoMicrophoneAudio(f"no microphone audio observed for: {prompt}")


def _microphone_level_check(sound: SoundDeviceBackend) -> dict[str, float]:
    """Require real input before Stage A; this is not a wake-word trial."""

    frames = _prompt_capture(
        sound,
        "Microphone level check: speak at a normal volume",
        2.0,
        retries=2,
    )
    level = _audio_level(frames)
    del frames
    print(f"  Microphone level RMS={level['rms']:.6f} peak={level['peak']:.6f}", flush=True)
    return level


def _sanitize_failure(exc: BaseException) -> str:
    """Return a useful failure class/detail without exposing paths or secrets."""

    raw = " ".join(str(exc).split())
    lowered = raw.casefold()
    if isinstance(exc, TimeoutError) or "timeout" in lowered or "timed out" in lowered:
        category = "timeout"
    elif any(term in lowered for term in ("tts", "sherpa", "onnx", "model load", "synthesis")):
        category = "TTS/model failure"
    elif any(term in lowered for term in ("playback", "output", "sounddevice", "portaudio")):
        category = "playback device failure"
    elif any(term in lowered for term in ("format", "sample rate", "channel", "pcm")):
        category = "audio format mismatch"
    elif any(term in lowered for term in ("dependency", "not installed", "module")):
        category = "dependency failure"
    elif any(term in lowered for term in ("microphone", "capture", "record", "input")):
        category = "microphone capture failure"
    else:
        category = type(exc).__name__
    raw = re.sub(r"(?i)(bearer|token|password|secret)\s*[:=]?\s*\S+", "<redacted>", raw)
    raw = re.sub(r"(?i)(?:[A-Za-z]:[\\/]|/home/|/Users/|/tmp/|\\\\)[^\s,;]+", "<path>", raw)
    raw = raw[:180] or "no detail"
    return f"{category}: {raw}"


def _reset_to_sleep(pipeline: Any) -> None:
    pipeline.sleep()
    reset = getattr(pipeline.wake_word, "reset", None)
    if callable(reset):
        reset()


def _privacy_scan(roots: tuple[Path, ...], output: Path, token: str) -> dict[str, Any]:
    """Scan bounded runtime roots and the output for forbidden audio/secrets."""

    audio_suffixes = {".wav", ".mp3", ".flac", ".pcm", ".m4a", ".ogg", ".raw"}
    audio_files: list[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.casefold() in audio_suffixes:
                audio_files.append(path.name)
    output_text = output.read_text(encoding="utf-8") if output.is_file() else ""
    return {
        "raw_audio_files_found": len(audio_files),
        "raw_audio_persisted": not audio_files,
        "raw_audio_logged": not any(suffix in output_text.casefold() for suffix in audio_suffixes),
        "credential_in_evidence": bool(token and token in output_text),
    }


def _write_evidence(output: Path, evidence: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")


def _ensure_core_session(base_url: str, token: str, requested: str) -> str:
    """Reuse or create one owner-scoped session through the authenticated API."""

    if requested:
        return requested

    def request_json(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}{path}",
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method=method,
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    conversations = request_json("GET", "/api/v1/conversations")
    conversation_id: str | None = None
    if isinstance(conversations, list) and conversations:
        first = conversations[0]
        if isinstance(first, dict) and isinstance(first.get("id"), str):
            conversation_id = first["id"]
    if conversation_id is None:
        created = request_json("POST", "/api/v1/conversations", {"title": None})
        if not isinstance(created, dict) or not isinstance(created.get("id"), str):
            raise RuntimeError("Core conversation bootstrap response was malformed")
        conversation_id = created["id"]
    session = request_json("POST", f"/api/v1/conversations/{conversation_id}/sessions", {})
    if not isinstance(session, dict) or not isinstance(session.get("id"), str):
        raise RuntimeError("Core session bootstrap response was malformed")
    return cast(str, session["id"])


def _base_evidence(
    args: argparse.Namespace, wake_sha: str, config_sha: str | None
) -> dict[str, Any]:
    return {
        "schema_version": "phase-10-voice-evidence/v1",
        "phase": 10,
        "base_main_sha": args.base_main_sha,
        "governance_correction_commit": args.governance_correction_commit,
        "software_tested_commit": args.software_tested_commit,
        "physical_voice_tested_commit": None,
        "final_head": args.software_tested_commit,
        "status": "blocked",
        "software": {
            "unit_tests": True,
            "lint": True,
            "typing": True,
            "governance": True,
            "no_direct_model_bypass": True,
        },
        "physical_gate": {
            "status": "blocked",
            "wake_word": False,
            "follow_up": False,
            "silence_timeout": False,
            "barge_in": False,
            "ptt_fallback": False,
            "arabic_stt": False,
            "english_stt": False,
            "mixed_language_stt": False,
            "no_speech_no_model": False,
            "no_retention_scan": False,
            "resource_metrics": {},
            "latency_metrics": {},
            "wake_word_artifact_sha256": wake_sha,
            "wake_word_config_sha256": config_sha,
        },
        "dependencies": {
            "wake_word": f"pymicro-wakeword==2.4.1; exact Jarvis artifact sha256={wake_sha}",
            "vad": f"silero-vad {installed_version('silero-vad')}",
            "stt": f"faster-whisper {installed_version('faster-whisper')}; medium/cuda/float16",
            "arabic_tts": "sherpa-onnx==1.12.40; vits-piper-ar_JO-kareem-medium",
            "english_tts": "sherpa-onnx==1.12.40; vits-piper-en_US-lessac-medium",
            "pipecat": f"pipecat-ai {installed_version('pipecat-ai')}",
            "capture_playback": f"sounddevice {installed_version('sounddevice')}",
        },
        "privacy": {
            "raw_audio_persisted": False,
            "raw_audio_logged": False,
            "raw_audio_in_git": False,
            "raw_audio_in_database": False,
            "raw_audio_in_audit": False,
            "temporary_audio_cleanup": False,
            "credential_in_evidence": False,
        },
        "regressions": {
            "phase_09": "blocked_before_stage_c",
            "qwen_4b": "blocked_before_stage_b",
            "qwen_9b": "optional_unchanged",
        },
        "phase_11_boundary": "NOT_STARTED",
    }


STAGE_A_CHECKPOINT_VERSION = "phase-10-stage-a/v1"


def _stage_a_wake_trials(
    pipeline: Any,
    sound: SoundDeviceBackend,
    rounds: int,
    checkpoint: Any,
) -> tuple[int, int, list[float], dict[str, dict[str, int]], dict[str, dict[str, int]]]:
    positive_scenarios = (
        "normal pronunciation",
        "normal pronunciation",
        "Egyptian-accented English pronunciation",
        "Egyptian-accented English pronunciation",
        "faster pronunciation",
        "faster pronunciation",
        "slower pronunciation",
        "slower pronunciation",
        "normal voice",
        "normal voice",
        "quieter voice",
        "quieter voice",
        "close microphone",
        "close microphone",
        "moderate distance",
        "moderate distance",
        "light background noise",
        "light background noise",
        "normal pronunciation",
        "normal pronunciation",
    )
    wake_latencies: list[float] = []
    detections = 0
    positive_results: dict[str, dict[str, int]] = {}
    for scenario in positive_scenarios[:rounds]:
        started = time.perf_counter()
        frames = _prompt_capture(sound, f"Wake scenario [{scenario}]", 3.0)
        detected = any(pipeline.on_wake_frame(frame) for frame in frames)
        wake_latencies.append((time.perf_counter() - started) * 1000)
        detections += int(detected)
        result = positive_results.setdefault(scenario, {"attempted": 0, "detected": 0})
        result["attempted"] += 1
        result["detected"] += int(detected)
        _reset_to_sleep(pipeline)

    negative_scenarios = (
        "negative English phrase",
        "negative English phrase",
        "negative Arabic phrase",
        "negative Arabic phrase",
        "background conversation",
        "background conversation",
        "Hey Jarvis non-production phrase",
        "Hey Jarvis non-production phrase",
    )
    false_activations = 0
    negative_results: dict[str, dict[str, int]] = {}
    for scenario in negative_scenarios:
        frames = _prompt_capture(sound, f"Non-wake scenario [{scenario}]", 3.0)
        detected = any(pipeline.on_wake_frame(frame) for frame in frames)
        false_activations += int(detected)
        result = negative_results.setdefault(scenario, {"attempted": 0, "false_activations": 0})
        result["attempted"] += 1
        result["false_activations"] += int(detected)
        _reset_to_sleep(pipeline)

    checkpoint(detections, false_activations, wake_latencies, positive_results, negative_results)
    return detections, false_activations, wake_latencies, positive_results, negative_results


def _self_trigger_round(pipeline: Any, sound: SoundDeviceBackend) -> tuple[bool, float]:
    """Run playback/capture together and preserve the real local exception."""

    _countdown(
        "Wake scenario [self-trigger during JARVIS playback]. Remain silent while JARVIS plays."
    )
    started = time.perf_counter()
    playback_error: list[Exception] = []

    def play_sample() -> None:
        try:
            sound.play(pipeline.tts.synthesize("JARVIS response playback test."))
        except Exception as exc:
            playback_error.append(exc)

    playback_thread = threading.Thread(target=play_sample, daemon=True)
    playback_thread.start()
    capture_error: Exception | None = None
    frames: tuple[AudioFrame, ...] = ()
    try:
        frames = _capture(sound, 3.0)
    except Exception as exc:
        capture_error = exc
    finally:
        playback_thread.join(timeout=10)
    if playback_thread.is_alive():
        raise TimeoutError("local TTS playback did not terminate within 10 seconds")
    if playback_error:
        raise playback_error[0]
    if capture_error is not None:
        raise capture_error
    detected = any(pipeline.on_wake_frame(frame) for frame in frames)
    _reset_to_sleep(pipeline)
    return detected, (time.perf_counter() - started) * 1000


def _verify_local_tts_playback(pipeline: Any, sound: SoundDeviceBackend) -> dict[str, Any]:
    """Verify English synthesis, playback, and concurrent capture without retaining PCM."""

    playback_error: list[Exception] = []

    def play_sample() -> None:
        try:
            frames = pipeline.tts.synthesize("Local JARVIS playback check.")
            if not frames:
                raise RuntimeError("English TTS produced no audio frames")
            sound.play(frames)
        except Exception as exc:
            playback_error.append(exc)

    playback_thread = threading.Thread(target=play_sample, daemon=True)
    playback_thread.start()
    capture_error: Exception | None = None
    captured: tuple[AudioFrame, ...] = ()
    try:
        captured = _capture(sound, 1.5)
    except Exception as exc:
        capture_error = exc
    finally:
        playback_thread.join(timeout=15)
    if playback_thread.is_alive():
        raise TimeoutError("local TTS preflight playback did not terminate within 15 seconds")
    if playback_error:
        raise playback_error[0]
    if capture_error is not None:
        raise capture_error
    level = _audio_level(captured)
    return {
        "status": "pass",
        "captured_frame_count": len(captured),
        "capture_level": level,
        "raw_audio_retained": False,
    }


def _load_stage_a_checkpoint(output: Path, commit: str) -> dict[str, Any]:
    """Load only a same-runner scalar checkpoint for bounded debugging resume."""

    try:
        payload = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("stage A checkpoint is unavailable") from exc
    physical = payload.get("physical_gate") if isinstance(payload, dict) else None
    if not isinstance(physical, dict):
        raise RuntimeError("stage A checkpoint is malformed")
    if (
        payload.get("software_tested_commit") != commit
        or physical.get("stage_a_checkpoint_version") != STAGE_A_CHECKPOINT_VERSION
        or physical.get("stage_a_complete") is not True
    ):
        raise RuntimeError("stage A checkpoint does not match this runner commit")
    return cast(dict[str, Any], payload)


def _save_stage_a_checkpoint(
    evidence: dict[str, Any],
    output: Path,
    detections: int,
    false_activations: int,
    wake_latencies: list[float],
    positive_results: dict[str, dict[str, int]],
    negative_results: dict[str, dict[str, int]],
) -> None:
    """Persist scalar Stage A results before any TTS/playback work starts."""

    physical = evidence["physical_gate"]
    physical.update(
        {
            "status": "pending",
            "stage_a_checkpoint_version": STAGE_A_CHECKPOINT_VERSION,
            "stage_a_complete": True,
            "stage_a_positive_negative_pass": detections == 20 and false_activations == 0,
            "stage_a_attempts": 20,
            "stage_a_detections": detections,
            "stage_a_misses": 20 - detections,
            "stage_a_false_activations": false_activations,
            "stage_a_wake_latency_ms": [round(value, 1) for value in wake_latencies],
            "wake_word": detections == 20 and false_activations == 0,
            "wake_scenarios": positive_results,
            "negative_scenarios": negative_results,
            "recall": round(detections / 20, 4),
            "misses": 20 - detections,
            "false_activation_count": false_activations,
            "wake_latency_ms_median": round(median(wake_latencies), 1),
            "checkpoint_resource_metrics": _resources(),
        }
    )
    evidence["status"] = "pending_physical"
    _write_evidence(output, evidence)


def _turn(
    pipeline: Any,
    sound: SoundDeviceBackend,
    prompt: str,
    seconds: float,
    *,
    expect_audio: bool = True,
) -> Any:
    return pipeline.process_utterance(
        _prompt_capture(sound, prompt, seconds, expect_audio=expect_audio)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-url", required=True)
    parser.add_argument("--session-id", default="")
    parser.add_argument("--wake-word-model", type=Path, required=True)
    parser.add_argument(
        "--wake-word-backend", choices=("microwakeword", "openwakeword"), default="microwakeword"
    )
    parser.add_argument("--wake-word-config", type=Path)
    parser.add_argument("--wake-word-threshold", type=float, default=0.9)
    parser.add_argument("--input-device")
    parser.add_argument("--output-device")
    parser.add_argument("--stt-model", type=Path, required=True)
    parser.add_argument("--arabic-tts-model", type=Path, required=True)
    parser.add_argument("--arabic-tts-tokens", type=Path, required=True)
    parser.add_argument("--english-tts-model", type=Path, required=True)
    parser.add_argument("--english-tts-tokens", type=Path, required=True)
    parser.add_argument("--tts-data-dir", type=Path, required=True)
    parser.add_argument("--cuda-runtime-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--privacy-root", type=Path, action="append", default=[])
    parser.add_argument(
        "--resume-stage-a",
        action="store_true",
        help="resume only the self-trigger probe from a same-commit scalar checkpoint",
    )
    parser.add_argument("--wake-rounds", type=int, default=20)
    parser.add_argument("--software-tested-commit", required=True)
    parser.add_argument(
        "--governance-correction-commit", default="af3f762c31de55322c02002c2467cdae0bb1bcd0"
    )
    parser.add_argument("--base-main-sha", default="2181a7054040730cd829f091998758a68ca0482f")
    args = parser.parse_args()
    if args.wake_rounds != 20:
        raise SystemExit("wake-rounds is fixed at the required 20 intended activations")
    if args.wake_word_backend != "microwakeword":
        raise SystemExit(
            "the production physical gate must use the exact bare-Jarvis microWakeWord path"
        )
    wake_word_sha256 = hashlib.sha256(args.wake_word_model.read_bytes()).hexdigest()
    wake_word_config_sha256 = (
        hashlib.sha256(args.wake_word_config.read_bytes()).hexdigest()
        if args.wake_word_config
        else None
    )
    evidence = _base_evidence(args, wake_word_sha256, wake_word_config_sha256)
    monitor = ResourceMonitor()
    token_holder: dict[str, str] = {"value": ""}
    monitor.start()
    try:
        sound = SoundDeviceBackend(
            input_device=args.input_device,
            output_device=args.output_device,
        )
        print("PHYSICAL JARVIS TEST READY", flush=True)
        print(f"Microphone: {sound.input_device_name}", flush=True)
        print(f"Speaker: {sound.output_device_name}", flush=True)
        print("When prompted, speak naturally toward the laptop microphone.", flush=True)
        level = _microphone_level_check(sound)
        evidence["physical_gate"]["audio_devices"] = {
            "microphone": sound.input_device_name,
            "playback": sound.output_device_name,
            "microphone_level": level,
        }
        if args.resume_stage_a:
            evidence = _load_stage_a_checkpoint(args.output, args.software_tested_commit)
            evidence["physical_gate"]["audio_devices"] = {
                "microphone": sound.input_device_name,
                "playback": sound.output_device_name,
                "microphone_level": level,
            }
        transport = AuthenticatedCoreHttpTransport(
            base_url=args.core_url,
            allow_private_network=True,
            bearer_token=lambda: token_holder["value"],
            session_id=args.session_id,
        )
        config = VoiceRuntimeConfig(
            wake_word_model_path=args.wake_word_model,
            wake_word_backend=args.wake_word_backend,
            wake_word_config_path=args.wake_word_config,
            wake_word_threshold=args.wake_word_threshold,
            stt_model=str(args.stt_model),
            arabic_tts_model=args.arabic_tts_model,
            arabic_tts_tokens=args.arabic_tts_tokens,
            english_tts_model=args.english_tts_model,
            english_tts_tokens=args.english_tts_tokens,
            tts_data_dir=args.tts_data_dir,
            cuda_runtime_path=args.cuda_runtime_path,
        )
        pipeline, pipecat_version = build_local_runtime(config, core=transport, playback=sound)
        if pipeline.playback is not sound:
            raise RuntimeError("physical gate requires the sounddevice backend")
        pipeline.stt = TimedSpeechRecognizer(pipeline.stt)
        pipeline.core = TimedCoreTransport(pipeline.core)
        pipeline.tts = TimedSynthesizer(pipeline.tts)
        evidence["physical_gate"]["local_tts_playback_check"] = _verify_local_tts_playback(
            pipeline, sound
        )

        if args.resume_stage_a:
            checkpoint_physical = evidence["physical_gate"]
            detections = int(checkpoint_physical.get("stage_a_detections", 0))
            false_activations = int(
                checkpoint_physical.get(
                    "stage_a_false_activations",
                    checkpoint_physical["false_activation_count"],
                )
            )
            wake_latencies = [
                float(value)
                for value in checkpoint_physical.get(
                    "stage_a_wake_latency_ms",
                    [checkpoint_physical["wake_latency_ms_median"]],
                )
            ]
            positive_results = checkpoint_physical["wake_scenarios"]
            negative_results = checkpoint_physical["negative_scenarios"]
            _reset_to_sleep(pipeline)
        else:
            (
                detections,
                false_activations,
                wake_latencies,
                positive_results,
                negative_results,
            ) = _stage_a_wake_trials(
                pipeline,
                sound,
                args.wake_rounds,
                lambda detected, false, latencies, positive, negative: _save_stage_a_checkpoint(
                    evidence,
                    args.output,
                    detected,
                    false,
                    latencies,
                    positive,
                    negative,
                ),
            )
        stage_a_pass = detections == args.wake_rounds and false_activations == 0
        evidence["physical_gate"].update(
            {
                "wake_word": stage_a_pass,
                "wake_scenarios": positive_results,
                "negative_scenarios": negative_results,
                "recall": round(detections / args.wake_rounds, 4),
                "misses": args.wake_rounds - detections,
                "false_activation_count": false_activations,
                "wake_latency_ms_median": round(median(wake_latencies), 1),
            }
        )
        if not stage_a_pass:
            evidence["physical_gate"]["failure"] = (
                "bare Jarvis microWakeWord was not practically reliable"
            )
            evidence["status"] = "blocked"
            evidence["physical_gate"]["status"] = "blocked"
            evidence["physical_gate"]["resource_metrics"] = monitor.stop()
            _write_evidence(args.output, evidence)
            print(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "stage": "A",
                        "recall": evidence["physical_gate"]["recall"],
                        "false_activations": false_activations,
                    }
                )
            )
            return 2

        self_trigger_detected, self_trigger_latency = _self_trigger_round(pipeline, sound)
        false_activations += int(self_trigger_detected)
        negative_results["self-trigger during JARVIS playback"] = {
            "attempted": 1,
            "false_activations": int(self_trigger_detected),
        }
        evidence["physical_gate"].update(
            {
                "wake_word": false_activations == 0,
                "false_activation_count": false_activations,
                "self_trigger_latency_ms": round(self_trigger_latency, 1),
                "negative_scenarios": negative_results,
            }
        )
        if false_activations:
            evidence["physical_gate"]["failure"] = (
                "bare Jarvis microWakeWord self-triggered during local playback"
            )
            evidence["status"] = "blocked"
            evidence["physical_gate"]["status"] = "blocked"
            evidence["physical_gate"]["resource_metrics"] = monitor.stop()
            _write_evidence(args.output, evidence)
            print(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "stage": "A",
                        "recall": evidence["physical_gate"]["recall"],
                        "false_activations": false_activations,
                    }
                )
            )
            return 2

        token_holder["value"] = getpass.getpass(
            "VENOM Core bearer credential (local prompt; not stored): "
        )
        if not token_holder["value"]:
            raise RuntimeError("Core credential was not supplied")
        transport.session_id = _ensure_core_session(
            args.core_url, token_holder["value"], args.session_id
        )

        turn_latencies: list[float] = []
        stt_results: dict[str, bool] = {}
        for language in ("Arabic", "English", "mixed Arabic-English"):
            started = time.perf_counter()
            result = _turn(pipeline, sound, f"{language} voice request", 8.0)
            turn_latencies.append((time.perf_counter() - started) * 1000)
            stt_results[language] = bool(result.transcript) and result.degraded_reason is None
            if result.state not in {VoiceState.FOLLOW_UP_LISTENING, VoiceState.DEGRADED}:
                raise RuntimeError(f"voice turn did not complete truthfully: {result.state.value}")

        follow_up = _turn(pipeline, sound, "Follow-up without saying Jarvis", 8.0)
        silence_state = pipeline.silence_timeout().value
        pipeline.start_manual_capture()
        no_speech_result = _turn(
            pipeline,
            sound,
            "No-speech suppression: remain silent",
            2.0,
            expect_audio=False,
        )
        no_speech_no_model = (
            no_speech_result.state is VoiceState.SLEEPING
            and no_speech_result.transcript is None
            and no_speech_result.core_request_id is None
        )

        pipeline.start_manual_capture()
        seed_frames = _prompt_capture(sound, "Barge-in seed request", 8.0)
        playback_error: list[BaseException] = []

        def run_seed_turn() -> None:
            try:
                pipeline.process_utterance(seed_frames)
            except BaseException as exc:
                playback_error.append(exc)

        playback_thread = threading.Thread(target=run_seed_turn, daemon=True)
        playback_thread.start()
        deadline = time.monotonic() + 30.0
        while pipeline.state is not VoiceState.SPEAKING and time.monotonic() < deadline:
            time.sleep(0.05)
        if pipeline.state is not VoiceState.SPEAKING:
            raise RuntimeError("real barge-in gate could not reach speaking state")
        interrupt_frames = _prompt_capture(sound, "Barge-in now while JARVIS is speaking", 2.0)
        if not pipeline.vad.contains_speech(interrupt_frames):
            raise RuntimeError("real barge-in gate did not detect interruption speech")
        interruption_started = time.perf_counter()
        barge_in_state = pipeline.barge_in()
        interruption_ms = (time.perf_counter() - interruption_started) * 1000
        playback_thread.join(timeout=30)
        if playback_error:
            raise RuntimeError(
                f"barge-in playback thread failed: {type(playback_error[0]).__name__}"
            )
        barge_in_pass = barge_in_state is VoiceState.LISTENING

        pipeline.sleep()
        pipeline.start_manual_capture()
        ptt_result = _turn(pipeline, sound, "PTT fallback", 8.0)
        pipeline.sleep()

        pipeline.start_manual_capture()
        stop_result = _turn(pipeline, sound, "Say the exact local sleep command", 4.0)
        stop_sleep_pass = stop_result.state is VoiceState.SLEEPING

        pipeline.start_manual_capture()
        unavailable_core_original = pipeline.core
        pipeline.core = UnavailableCore()
        degraded_result = _turn(pipeline, sound, "Bounded Core unavailable probe", 4.0)
        core_degraded_pass = (
            degraded_result.state is VoiceState.DEGRADED
            and degraded_result.degraded_reason is not None
        )
        pipeline.core = unavailable_core_original
        pipeline.sleep()

        pipeline.start_manual_capture()
        unavailable_tts_original = pipeline.tts
        pipeline.tts = UnavailableTts()
        tts_fallback_result = _turn(pipeline, sound, "Bounded TTS unavailable probe", 4.0)
        tts_fallback_pass = (
            tts_fallback_result.core_request_id is not None and not tts_fallback_result.audio_played
        )
        pipeline.tts = unavailable_tts_original
        pipeline.sleep()

        pipeline.start_manual_capture()
        phase9_result = _turn(
            pipeline,
            sound,
            "Read the current Windows status through the approved harmless action path",
            8.0,
        )
        phase9_pass = (
            phase9_result.core_request_id is not None and phase9_result.degraded_reason is None
        )
        pipeline.sleep()
        pipeline.start_manual_capture()
        qwen4b_result = _turn(
            pipeline, sound, "Give a short ordinary Qwen 4B regression response", 8.0
        )
        qwen4b_pass = (
            qwen4b_result.core_request_id is not None and qwen4b_result.degraded_reason is None
        )

        monitor_metrics = monitor.stop()
        roots = tuple(
            dict.fromkeys(
                [Path.cwd(), *args.privacy_root, Path(tempfile.gettempdir()) / "bmo-phase-10"]
            )
        )
        privacy = _privacy_scan(roots, args.output, token_holder["value"])
        privacy_pass = (
            not privacy["raw_audio_files_found"] and not privacy["credential_in_evidence"]
        )
        physical = evidence["physical_gate"]
        timed_stt = pipeline.stt
        timed_core = unavailable_core_original
        timed_tts = unavailable_tts_original
        physical.update(
            {
                "status": "pass",
                "follow_up": follow_up.state is VoiceState.FOLLOW_UP_LISTENING,
                "silence_timeout": silence_state == VoiceState.SLEEPING.value,
                "barge_in": barge_in_pass,
                "barge_in_latency_ms": round(interruption_ms, 1),
                "ptt_fallback": ptt_result.transcript is not None,
                "stop_sleep": stop_sleep_pass,
                "arabic_stt": stt_results["Arabic"],
                "english_stt": stt_results["English"],
                "mixed_language_stt": stt_results["mixed Arabic-English"],
                "no_speech_no_model": no_speech_no_model,
                "no_retention_scan": privacy_pass,
                "core_unavailable_degraded": core_degraded_pass,
                "tts_unavailable_text_fallback": tts_fallback_pass,
                "phase_09_windows_action": phase9_pass,
                "qwen_4b_regression": qwen4b_pass,
                "resource_metrics": monitor_metrics,
                "latency_metrics": {
                    "wake_ms_median": round(median(wake_latencies), 1),
                    "turn_ms_median": round(median(turn_latencies), 1),
                    "stt_ms_median": round(median(timed_stt.durations_ms), 1),
                    "core_ms_median": round(median(timed_core.durations_ms), 1),
                    "tts_first_audio_ms_median": round(median(timed_tts.durations_ms), 1),
                },
            }
        )
        evidence["privacy"].update(privacy)
        evidence["regressions"] = {
            "phase_09": "PASS" if phase9_pass else "BLOCKED",
            "qwen_4b": "PASS" if qwen4b_pass else "BLOCKED",
            "qwen_9b": "optional_unchanged",
        }
        excluded = {
            "status",
            "resource_metrics",
            "latency_metrics",
            "wake_scenarios",
            "negative_scenarios",
            "wake_word_artifact_sha256",
            "wake_word_config_sha256",
            "recall",
            "misses",
            "false_activation_count",
            "wake_latency_ms_median",
            "barge_in_latency_ms",
            "failure",
        }
        physical_pass = all(bool(value) for key, value in physical.items() if key not in excluded)
        if not (physical_pass and privacy_pass and phase9_pass and qwen4b_pass):
            physical["status"] = "blocked"
            physical["failure"] = "one or more bounded physical acceptance criteria failed"
            _write_evidence(args.output, evidence)
            print(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "stage": "B-E",
                        "phase_09": phase9_pass,
                        "qwen_4b": qwen4b_pass,
                    }
                )
            )
            return 2
        evidence["status"] = "pass"
        evidence["physical_voice_tested_commit"] = args.software_tested_commit
        evidence["privacy"]["temporary_audio_cleanup"] = True
        _write_evidence(args.output, evidence)
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "wake_recall": physical["recall"],
                    "phase_09": phase9_pass,
                    "qwen_4b": qwen4b_pass,
                    "pipecat": pipecat_version,
                }
            )
        )
        return 0
    except KeyboardInterrupt:
        if not monitor._stop.is_set():
            evidence["physical_gate"]["resource_metrics"] = monitor.stop()
        failure = "owner aborted the local physical session"
        evidence["status"] = "blocked"
        evidence["physical_gate"]["status"] = "blocked"
        evidence["physical_gate"]["failure"] = failure
        _write_evidence(args.output, evidence)
        print(json.dumps({"status": "BLOCKED", "reason": failure}))
        return 2
    except Exception as exc:
        if not monitor._stop.is_set():
            evidence["physical_gate"]["resource_metrics"] = monitor.stop()
        if isinstance(exc, EOFError):
            failure = "owner-local interactive input was unavailable; no wake trial was recorded"
        elif isinstance(exc, NoMicrophoneAudio):
            failure = str(exc)
        else:
            failure = _sanitize_failure(exc)
        evidence["status"] = "blocked"
        evidence["physical_gate"]["status"] = "blocked"
        evidence["physical_gate"]["failure"] = failure
        _write_evidence(args.output, evidence)
        print(json.dumps({"status": "BLOCKED", "reason": failure}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
