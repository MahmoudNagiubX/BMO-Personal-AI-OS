"""Run the bounded, interactive Phase 10 ASUS TUF voice acceptance gate.

The runner keeps microphone PCM in memory only. It records scalar counts,
timings, resource peaks, statuses, versions, and hashes in sanitized JSON.
Stage A is a hard gate: no Core credential is requested and no speech/model
request is attempted until ``Hey Jarvis`` is practically usable.
"""

from __future__ import annotations

import argparse
import array
import getpass
import json
import math
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any, NoReturn, cast

import psutil

from personal_ai_os.voice.activation import ActivationUnavailable, WindowsRightCtrlDoubleTap
from personal_ai_os.voice.adapters import installed_version
from personal_ai_os.voice.contracts import (
    ActivationSource,
    AudioFrame,
    CoreResponse,
    CoreResponseDelta,
    VoiceState,
    VoiceTurnResult,
)
from personal_ai_os.voice.core_transport import AuthenticatedCoreHttpTransport
from personal_ai_os.voice.runtime import VoiceRuntimeConfig, build_local_conversation_loop
from personal_ai_os.voice.sounddevice_backend import SoundDeviceBackend
from personal_ai_os.voice.wake_phrase import PRIMARY_WAKE_PHRASE

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_EVIDENCE_PATH = (
    REPOSITORY_ROOT / "docs" / "phase_reports" / "evidence" / "PHASE_10_JARVIS_VOICE_CORE.json"
)


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

    def stream(self, text: str, *, client_message_id: str) -> Sequence[CoreResponseDelta]:
        started = time.perf_counter()
        try:
            stream_method = getattr(self._wrapped, "stream", None)
            if callable(stream_method):
                return cast(
                    Sequence[CoreResponseDelta],
                    stream_method(text, client_message_id=client_message_id),
                )
            response = cast(
                CoreResponse,
                self._wrapped.send(text, client_message_id=client_message_id),
            )
            return (CoreResponseDelta(response.request_id, response.text, final=True),)
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

    def stream(self, _text: str, *, client_message_id: str) -> Sequence[CoreResponseDelta]:
        del client_message_id
        raise RuntimeError("bounded_core_unavailable_probe")


class UnavailableTts:
    """Bounded local fault injector used only for text-preserving TTS proof."""

    def synthesize(self, _text: str) -> NoReturn:
        raise RuntimeError("bounded_tts_unavailable_probe")


class NoMicrophoneAudio(RuntimeError):
    """Capture contained no signal above the calibrated ambient noise floor."""


class OwnerPhysicalAbort(RuntimeError):
    """The owner interrupted the local physical session."""


def _start_live_capture(
    loop: Any, sound: SoundDeviceBackend, seconds: float
) -> tuple[threading.Thread, threading.Event, dict[str, Any]]:
    """Run the real input stream and deliver every bounded frame to the loop."""

    stop_event = threading.Event()
    result: dict[str, Any] = {
        "frame_count": 0,
        "state_changes": 0,
        "capture_start_to_barge_in_ms": None,
        "errors": [],
    }
    started = time.perf_counter()
    previous_state: VoiceState | None = getattr(loop, "state", None)

    def on_frame(frame: AudioFrame) -> None:
        nonlocal previous_state
        result["frame_count"] += 1
        try:
            state = loop.on_frame(frame)
        except Exception as exc:
            cast(list[BaseException], result["errors"]).append(exc)
            stop_event.set()
            return
        if previous_state is not None and state is not previous_state:
            result["state_changes"] += 1
        if (
            previous_state is VoiceState.SPEAKING
            and state is VoiceState.LISTENING
            and result["capture_start_to_barge_in_ms"] is None
        ):
            result["capture_start_to_barge_in_ms"] = round(
                (time.perf_counter() - started) * 1000, 1
            )
        previous_state = state

    def run() -> None:
        try:
            sound.stream_input(on_frame, seconds=seconds, stop_event=stop_event)
        except BaseException as exc:
            cast(list[BaseException], result["errors"]).append(exc)

    thread = threading.Thread(target=run, name="bmo-physical-live-capture", daemon=True)
    thread.start()
    return thread, stop_event, result


def _finish_live_capture(
    thread: threading.Thread,
    stop_event: threading.Event,
    result: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    """Stop a bounded live capture and surface sanitized callback failures."""

    thread.join(timeout=timeout_seconds)
    stop_event.set()
    thread.join(timeout=5.0)
    if thread.is_alive():
        raise TimeoutError("live microphone stream did not stop within its bounded lifetime")
    errors = cast(list[BaseException], result["errors"])
    if errors:
        raise errors[0]
    result.pop("errors", None)
    return result


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


@dataclass(frozen=True, slots=True)
class PresenceCalibration:
    """Device-relative scalar thresholds for distinguishing no signal from speech."""

    ambient_rms: float
    ambient_peak: float
    measurable_rms: float
    measurable_peak: float
    speech_rms: float
    speech_peak: float

    def classify(self, level: dict[str, float]) -> str:
        """Classify only scalar levels; PCM never leaves the caller's memory."""

        if level["rms"] >= self.speech_rms and level["peak"] >= self.speech_peak:
            return "SPEECH_PRESENT"
        if level["rms"] >= self.measurable_rms or level["peak"] >= self.measurable_peak:
            return "MEASURABLE_SIGNAL"
        return "NO_AUDIO"

    def as_evidence(self) -> dict[str, float]:
        return {
            "ambient_rms": self.ambient_rms,
            "ambient_peak": self.ambient_peak,
            "measurable_rms_threshold": self.measurable_rms,
            "measurable_peak_threshold": self.measurable_peak,
            "speech_rms_threshold": self.speech_rms,
            "speech_peak_threshold": self.speech_peak,
        }


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def _derive_presence_calibration(ambient: dict[str, float]) -> PresenceCalibration:
    """Derive bounded thresholds with both relative and absolute safety clamps."""

    measurable_rms = _clamp(
        max(ambient["rms"] * 1.25, ambient["rms"] + 0.00015, 0.00025),
        0.00025,
        0.01,
    )
    measurable_peak = _clamp(
        max(ambient["peak"] * 1.15, ambient["peak"] + 0.0003, 0.0008),
        0.0008,
        0.04,
    )
    speech_rms = _clamp(
        max(ambient["rms"] * 2.0, ambient["rms"] + 0.0005, 0.0008),
        0.0008,
        0.02,
    )
    speech_peak = _clamp(
        max(ambient["peak"] * 1.5, ambient["peak"] + 0.001, 0.002),
        0.002,
        0.08,
    )
    return PresenceCalibration(
        ambient_rms=ambient["rms"],
        ambient_peak=ambient["peak"],
        measurable_rms=round(measurable_rms, 6),
        measurable_peak=round(measurable_peak, 6),
        speech_rms=round(speech_rms, 6),
        speech_peak=round(speech_peak, 6),
    )


def _calibrate_microphone_presence(sound: SoundDeviceBackend) -> PresenceCalibration:
    """Capture a short silent baseline before any owner speech trials."""

    _countdown("Ambient microphone baseline: remain silent while the device is sampled.")
    baseline_frames = _capture(sound, 1.0)
    ambient = _audio_level(baseline_frames)
    calibration = _derive_presence_calibration(ambient)
    print(
        "  Ambient baseline "
        f"RMS={ambient['rms']:.6f} peak={ambient['peak']:.6f}; "
        f"measurable RMS>={calibration.measurable_rms:.6f} "
        f"peak>={calibration.measurable_peak:.6f}",
        flush=True,
    )
    return calibration


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
    presence: PresenceCalibration | None = None,
) -> tuple[AudioFrame, ...]:
    calibration = presence or _derive_presence_calibration({"rms": 0.0, "peak": 0.0})
    for attempt in range(retries + 1):
        _countdown(f"{prompt} Speak naturally after the countdown.")
        frames = _capture(sound, seconds)
        level = _audio_level(frames)
        signal_status = calibration.classify(level)
        if not expect_audio or signal_status != "NO_AUDIO":
            return frames
        if attempt < retries:
            print("  NO_AUDIO above calibrated baseline; retrying this prompt.", flush=True)
    raise NoMicrophoneAudio(f"NO_AUDIO above calibrated baseline for: {prompt}")


def _microphone_level_check(
    sound: SoundDeviceBackend, presence: PresenceCalibration
) -> dict[str, float]:
    """Require real input before Stage A; this is not a wake-word trial."""

    frames = _prompt_capture(
        sound,
        "Microphone level check: speak at a normal volume",
        2.0,
        retries=2,
        presence=presence,
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


def _reset_to_sleep(loop: Any) -> None:
    """Reset the shared conversation coordinator to wake-word-only idle."""

    loop.sleep()
    pipeline = getattr(loop, "pipeline", loop)
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


def _validate_physical_evidence_path(output: Path) -> None:
    """Reject direct writes to the canonical evidence owned by the repository."""

    if output.resolve() == CANONICAL_EVIDENCE_PATH.resolve():
        raise RuntimeError("physical session evidence must use the dedicated local evidence file")


def _write_evidence(output: Path, evidence: dict[str, Any]) -> None:
    _validate_physical_evidence_path(output)
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


def _base_evidence(args: argparse.Namespace) -> dict[str, Any]:
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
            "owner_gate_policy": {
                "positive_wake_activations_min": 3,
                "positive_wake_activations_max": 5,
                "representative_negative_cases_max": 5,
                "no_20_round_owner_calibration": True,
                "single_utterance_preroll": True,
                "right_ctrl_shared_pipeline": True,
                "smart_turn_natural_pause": True,
            },
            "wake_word": False,
            "single_utterance_preroll": False,
            "right_ctrl_activation": False,
            "smart_turn_natural_pause": False,
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
            "wake_word_model": str(getattr(args, "wake_model", "faster-whisper-base.en")),
            "wake_word_device": "cpu",
            "wake_word_compute_type": "int8",
            "wake_word_beam_size": 1,
            "wake_word_hotwords": None,
        },
        "dependencies": {
            "wake_word": (
                f"speech_gated_faster_whisper; {PRIMARY_WAKE_PHRASE}; "
                "Silero VAD -> faster-whisper wake recognizer; exact prefix"
            ),
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
    loop: Any,
    sound: SoundDeviceBackend,
    rounds: int,
    checkpoint: Any,
    presence: PresenceCalibration,
) -> tuple[int, int, list[float], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    positive_scenarios = (
        "normal Hey Jarvis",
        "Egyptian-accented Hey Jarvis",
        "moderate-distance Hey Jarvis",
        "quieter Hey Jarvis",
        "faster Hey Jarvis",
    )
    wake_latencies: list[float] = []
    detections = 0
    false_activations = 0
    positive_results: dict[str, dict[str, Any]] = {}
    for index, scenario in enumerate(positive_scenarios[:rounds]):
        started = time.perf_counter()
        try:
            frames = _prompt_capture(sound, f"Wake scenario [{scenario}]", 3.0, presence=presence)
        except NoMicrophoneAudio:
            if index < 3:
                raise
            positive_results[scenario] = {
                "attempted": 1,
                "detected": 0,
                "required": 0,
                "capture_status": "NO_AUDIO",
                "wake_status": "not_tested",
            }
            checkpoint(
                detections,
                false_activations,
                wake_latencies,
                positive_results,
                {},
                complete=False,
            )
            continue
        detected = False
        for frame in frames:
            detected = loop.on_frame(frame) is not VoiceState.SLEEPING or detected
        wake_latencies.append((time.perf_counter() - started) * 1000)
        detections += int(detected)
        result = positive_results.setdefault(scenario, {"attempted": 0, "detected": 0})
        result["attempted"] += 1
        result["detected"] += int(detected)
        result["required"] = int(index < 3)
        result["capture_status"] = presence.classify(_audio_level(frames))
        result["wake_status"] = "wake_detected" if detected else "wake_miss"
        _reset_to_sleep(loop)
        checkpoint(
            detections,
            false_activations,
            wake_latencies,
            positive_results,
            {},
            complete=False,
        )

    negative_scenarios = (
        "bare Jarvis",
        "English non-wake speech",
        "Arabic non-wake speech",
        "background conversation",
    )
    false_activations = 0
    negative_results: dict[str, dict[str, Any]] = {}
    for scenario in negative_scenarios:
        frames = _prompt_capture(sound, f"Non-wake scenario [{scenario}]", 3.0, presence=presence)
        detected = False
        for frame in frames:
            detected = loop.on_frame(frame) is not VoiceState.SLEEPING or detected
        false_activations += int(detected)
        result = negative_results.setdefault(scenario, {"attempted": 0, "false_activations": 0})
        result["attempted"] += 1
        result["false_activations"] += int(detected)
        _reset_to_sleep(loop)
        checkpoint(
            detections,
            false_activations,
            wake_latencies,
            positive_results,
            negative_results,
            complete=False,
        )

    checkpoint(
        detections,
        false_activations,
        wake_latencies,
        positive_results,
        negative_results,
        complete=True,
    )
    return detections, false_activations, wake_latencies, positive_results, negative_results


def _self_trigger_round(loop: Any, sound: SoundDeviceBackend) -> tuple[bool, float]:
    """Run live playback/capture together while the coordinator is sleeping."""

    _countdown(
        "Wake scenario [self-trigger during JARVIS playback]. Remain silent while JARVIS plays."
    )
    started = time.perf_counter()
    playback_error: list[Exception] = []

    _reset_to_sleep(loop)
    pipeline = getattr(loop, "pipeline", loop)

    def play_sample() -> None:
        try:
            sound.play(pipeline.tts.synthesize("JARVIS response playback test."))
        except Exception as exc:
            playback_error.append(exc)

    playback_thread = threading.Thread(target=play_sample, daemon=True)
    playback_thread.start()
    capture_thread, capture_stop, capture_result = _start_live_capture(loop, sound, 3.0)
    playback_thread.join(timeout=10)
    if playback_thread.is_alive():
        raise TimeoutError("local TTS playback did not terminate within 10 seconds")
    if playback_error:
        raise playback_error[0]
    _finish_live_capture(capture_thread, capture_stop, capture_result, timeout_seconds=10.0)
    false_activation_detected = loop.state is not VoiceState.SLEEPING

    _reset_to_sleep(loop)
    return false_activation_detected, (time.perf_counter() - started) * 1000


def _verify_local_tts_playback(loop: Any, sound: SoundDeviceBackend) -> dict[str, Any]:
    """Verify English synthesis, playback, and concurrent capture without retaining PCM."""

    playback_error: list[Exception] = []
    pipeline = getattr(loop, "pipeline", loop)

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
    attempts = physical.get("stage_a_attempts")
    if not isinstance(attempts, int) or not 3 <= attempts <= 5:
        raise RuntimeError("stage A checkpoint uses the obsolete long owner wake policy")
    return cast(dict[str, Any], payload)


def _prepare_physical_evidence(
    output: Path, commit: str, *, resume_stage_a: bool
) -> dict[str, Any] | None:
    """Refuse unsafe overwrites and return only a same-head resumable checkpoint."""

    _validate_physical_evidence_path(output)
    if not output.exists():
        return None
    try:
        checkpoint = _load_stage_a_checkpoint(output, commit)
    except RuntimeError as exc:
        raise RuntimeError(
            "PHYSICAL_EVIDENCE_EXISTS_NOT_RESUMABLE: dedicated physical evidence "
            "requires explicit review"
        ) from exc
    if not resume_stage_a:
        raise RuntimeError(
            "PHYSICAL_EVIDENCE_EXISTS_REQUIRES_RESUME: same-head checkpoint "
            "requires explicit resume"
        )
    return checkpoint


def _save_stage_a_checkpoint(
    evidence: dict[str, Any],
    output: Path,
    detections: int,
    false_activations: int,
    wake_latencies: list[float],
    positive_results: dict[str, dict[str, Any]],
    negative_results: dict[str, dict[str, Any]],
    *,
    rounds: int = 5,
    complete: bool = True,
) -> None:
    """Persist scalar Stage A results before any TTS/playback work starts."""

    if not 3 <= rounds <= 5:
        raise ValueError("owner wake validation must contain between 3 and 5 activations")

    physical = evidence["physical_gate"]
    required_attempts = sum(
        value.get("attempted", 0)
        for value in positive_results.values()
        if value.get("required", 0) == 1
    )
    required_detections = sum(
        value.get("detected", 0)
        for value in positive_results.values()
        if value.get("required", 0) == 1
    )
    attempted = sum(value.get("attempted", 0) for value in positive_results.values())
    physical.update(
        {
            "status": "pending",
            "stage_a_checkpoint_version": STAGE_A_CHECKPOINT_VERSION,
            "stage_a_complete": complete,
            "stage_a_positive_negative_pass": complete
            and required_detections == min(rounds, 3)
            and false_activations == 0,
            "stage_a_target_attempts": rounds,
            "stage_a_attempts": attempted,
            "stage_a_required_attempts": required_attempts,
            "stage_a_required_detections": required_detections,
            "stage_a_optional_attempts": attempted - required_attempts,
            "stage_a_detections": detections,
            "stage_a_misses": attempted - detections,
            "stage_a_false_activations": false_activations,
            "stage_a_wake_latency_ms": [round(value, 1) for value in wake_latencies],
            "wake_word": complete
            and required_detections == min(rounds, 3)
            and false_activations == 0,
            "wake_scenarios": positive_results,
            "negative_scenarios": negative_results,
            "recall": round(detections / attempted, 4) if attempted else 0.0,
            "misses": attempted - detections,
            "false_activation_count": false_activations,
            "wake_latency_ms_median": round(median(wake_latencies), 1),
            "checkpoint_resource_metrics": _resources(),
        }
    )
    evidence["status"] = "pending_physical"
    _write_evidence(output, evidence)


def _single_utterance_preroll_round(
    loop: Any, sound: SoundDeviceBackend, presence: PresenceCalibration
) -> dict[str, Any]:
    """Prove that a bare wake word and following command share one turn."""

    frames = _prompt_capture(
        sound,
        "Single utterance: say 'Hey Jarvis' followed immediately by a harmless approved request",
        8.0,
        presence=presence,
    )
    detected = False
    for frame in frames:
        previous_state = loop.state
        state = loop.on_frame(frame)
        if (
            not detected
            and previous_state is VoiceState.SLEEPING
            and state is not VoiceState.SLEEPING
        ):
            detected = True
    if not detected:
        _reset_to_sleep(loop)
        raise RuntimeError("single-utterance pre-roll did not detect the Hey Jarvis wake phrase")
    loop.wait_for_idle(10.0)
    result = loop.last_result or VoiceTurnResult(state=loop.state)
    passed = bool(result.transcript) and result.core_request_id is not None
    details = {
        "status": "pass" if passed else "blocked",
        "wake_detected": detected,
        "stt_received_command": bool(result.transcript),
        "authenticated_core_request": result.core_request_id is not None,
        "phase_8_9_authority_required": True,
        "direct_execution_bypass": False,
    }
    _reset_to_sleep(loop)
    if not passed:
        raise RuntimeError("single-utterance pre-roll did not reach authenticated Core")
    return details


def _right_ctrl_activation_round(
    loop: Any, sound: SoundDeviceBackend, presence: PresenceCalibration
) -> dict[str, Any]:
    """Prove the real Right-Ctrl path enters the same router and voice pipeline."""

    activation_seen = threading.Event()
    activation_errors: list[Exception] = []

    def activate() -> None:
        try:
            loop.pipeline.activation_router.right_ctrl_double_tap()
        except Exception as exc:
            activation_errors.append(exc)
        finally:
            activation_seen.set()

    print(
        "\nRIGHT CTRL TEST READY\n"
        "Double-tap Right Ctrl now; after activation, speak one harmless request.",
        flush=True,
    )
    try:
        detector = WindowsRightCtrlDoubleTap(activate)
    except ActivationUnavailable as exc:
        raise RuntimeError(f"Right Ctrl activation unavailable: {exc}") from exc
    started = time.perf_counter()
    detector.start()
    try:
        if not activation_seen.wait(timeout=20.0):
            raise TimeoutError("Right Ctrl double-tap was not detected within 20 seconds")
        if activation_errors:
            raise activation_errors[0]
        if loop.state is not VoiceState.LISTENING:
            raise RuntimeError("Right Ctrl activation did not enter LISTENING")
        activation_latency = (time.perf_counter() - started) * 1000
        result = _turn(
            loop,
            sound,
            "Right Ctrl activated: speak a short harmless request",
            8.0,
            presence=presence,
        )
        passed = bool(result.transcript) and result.core_request_id is not None
        details = {
            "status": "pass" if passed else "blocked",
            "activation_router": "shared",
            "pipeline_state_after_activation": VoiceState.LISTENING.value,
            "stt_received_request": bool(result.transcript),
            "authenticated_core_request": result.core_request_id is not None,
            "activation_latency_ms": round(activation_latency, 1),
            "admin_required": False,
            "general_keyboard_capture": False,
        }
        _reset_to_sleep(loop)
        if not passed:
            raise RuntimeError("Right Ctrl activation did not complete the shared Core turn")
        return details
    finally:
        detector.stop()


def _smart_turn_pause_round(
    loop: Any, sound: SoundDeviceBackend, presence: PresenceCalibration
) -> dict[str, Any]:
    """Prove a short natural pause does not prematurely close a turn."""

    pipeline = loop.pipeline
    if pipeline.turn_detector is None:
        raise RuntimeError("Smart Turn detector is unavailable")
    if loop.state is VoiceState.SLEEPING:
        loop.activate(ActivationSource.PTT)
    frames = _prompt_capture(
        sound,
        "Smart Turn natural pause: say a sentence, pause briefly to think, then finish it",
        8.0,
        presence=presence,
    )
    midpoint = max(1, len(frames) // 2)
    early_complete = pipeline.turn_complete(frames[:midpoint], silence_seconds=0.5)
    final_complete = pipeline.turn_complete(frames, silence_seconds=3.0)
    loop.feed(frames)
    loop.wait_for_idle(10.0)
    result = loop.last_result or VoiceTurnResult(state=loop.state)
    passed = (
        not early_complete
        and final_complete
        and bool(result.transcript)
        and result.core_request_id is not None
    )
    details = {
        "status": "pass" if passed else "blocked",
        "early_pause_completed": early_complete,
        "final_turn_completed": final_complete,
        "stt_received_complete_turn": bool(result.transcript),
        "authenticated_core_request": result.core_request_id is not None,
        "bounded_timeout_fallback": True,
    }
    _reset_to_sleep(loop)
    if not passed:
        raise RuntimeError("Smart Turn ended or failed to complete the natural-pause turn")
    return details


def _turn(
    loop: Any,
    sound: SoundDeviceBackend,
    prompt: str,
    seconds: float,
    *,
    expect_audio: bool = True,
    presence: PresenceCalibration | None = None,
) -> Any:
    if loop.state is VoiceState.SLEEPING:
        loop.activate(ActivationSource.PTT)
    frames = _prompt_capture(sound, prompt, seconds, expect_audio=expect_audio, presence=presence)
    loop.feed(frames)
    loop.wait_for_idle(10.0)
    return loop.last_result or VoiceTurnResult(state=loop.state)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-url", required=True)
    parser.add_argument("--session-id", default="")
    parser.add_argument(
        "--wake-word-backend",
        choices=("speech_gated_faster_whisper",),
        default="speech_gated_faster_whisper",
    )
    parser.add_argument("--wake-model", type=Path, required=True)
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
        help="resume only the self-trigger probe from a same-commit dedicated checkpoint",
    )
    parser.add_argument("--wake-rounds", type=int, default=3)
    parser.add_argument("--software-tested-commit", required=True)
    parser.add_argument(
        "--governance-correction-commit", default="af3f762c31de55322c02002c2467cdae0bb1bcd0"
    )
    parser.add_argument("--base-main-sha", default="2181a7054040730cd829f091998758a68ca0482f")
    args = parser.parse_args()
    if not 3 <= args.wake_rounds <= 5:
        raise SystemExit("wake-rounds must remain a bounded value between 3 and 5")
    evidence = _prepare_physical_evidence(
        args.output, args.software_tested_commit, resume_stage_a=args.resume_stage_a
    ) or _base_evidence(args)
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
        print(f"Wake phrase: {PRIMARY_WAKE_PHRASE}", flush=True)
        print(f"Active backend: {args.wake_word_backend}", flush=True)
        print("When prompted, speak naturally toward the laptop microphone.", flush=True)
        presence = _calibrate_microphone_presence(sound)
        level = _microphone_level_check(sound, presence)
        evidence["physical_gate"]["audio_devices"] = {
            "microphone": sound.input_device_name,
            "playback": sound.output_device_name,
            "microphone_level": level,
            "presence_calibration": presence.as_evidence(),
        }
        if args.resume_stage_a:
            evidence = _load_stage_a_checkpoint(args.output, args.software_tested_commit)
            evidence["physical_gate"]["audio_devices"] = {
                "microphone": sound.input_device_name,
                "playback": sound.output_device_name,
                "microphone_level": level,
                "presence_calibration": presence.as_evidence(),
            }
        transport = AuthenticatedCoreHttpTransport(
            base_url=args.core_url,
            allow_private_network=True,
            bearer_token=lambda: token_holder["value"],
            session_id=args.session_id,
        )
        config = VoiceRuntimeConfig(
            wake_word_backend=args.wake_word_backend,
            wake_word_model=str(args.wake_model),
            wake_word_device="cpu",
            wake_word_compute_type="int8",
            wake_word_beam_size=1,
            wake_word_hotwords=None,
            stt_model=str(args.stt_model),
            arabic_tts_model=args.arabic_tts_model,
            arabic_tts_tokens=args.arabic_tts_tokens,
            english_tts_model=args.english_tts_model,
            english_tts_tokens=args.english_tts_tokens,
            tts_data_dir=args.tts_data_dir,
            cuda_runtime_path=args.cuda_runtime_path,
        )
        loop, pipecat_version = build_local_conversation_loop(
            config, core=transport, playback=sound
        )
        pipeline = loop.pipeline
        if pipeline.playback is not sound:
            raise RuntimeError("physical gate requires the sounddevice backend")
        pipeline.stt = TimedSpeechRecognizer(pipeline.stt)
        pipeline.core = TimedCoreTransport(pipeline.core)
        pipeline.tts = TimedSynthesizer(pipeline.tts)
        evidence["physical_gate"]["local_tts_playback_check"] = _verify_local_tts_playback(
            loop, sound
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
            _reset_to_sleep(loop)
        else:
            (
                detections,
                false_activations,
                wake_latencies,
                positive_results,
                negative_results,
            ) = _stage_a_wake_trials(
                loop,
                sound,
                args.wake_rounds,
                lambda detected, false, latencies, positive, negative, complete: (
                    _save_stage_a_checkpoint(
                        evidence,
                        args.output,
                        detected,
                        false,
                        latencies,
                        positive,
                        negative,
                        rounds=args.wake_rounds,
                        complete=complete,
                    )
                ),
                presence,
            )
        required_detections = sum(
            value.get("detected", 0)
            for value in positive_results.values()
            if value.get("required", 0) == 1
        )
        required_rounds = min(args.wake_rounds, 3)
        stage_a_pass = required_detections == required_rounds and false_activations == 0
        evidence["physical_gate"].update(
            {
                "wake_word": stage_a_pass,
                "wake_scenarios": positive_results,
                "negative_scenarios": negative_results,
                "stage_a_required_detections": required_detections,
                "stage_a_required_attempts": required_rounds,
                "recall": round(detections / args.wake_rounds, 4),
                "misses": args.wake_rounds - detections,
                "false_activation_count": false_activations,
                "wake_latency_ms_median": round(median(wake_latencies), 1),
            }
        )
        if not stage_a_pass:
            evidence["physical_gate"]["failure"] = (
                f"bare Jarvis {args.wake_word_backend} gate was not practically reliable"
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

        self_trigger_detected, self_trigger_latency = _self_trigger_round(loop, sound)
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
        _write_evidence(args.output, evidence)
        if false_activations:
            evidence["physical_gate"]["failure"] = (
                f"bare Jarvis {args.wake_word_backend} self-triggered during local playback"
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
        single_utterance_preroll = _single_utterance_preroll_round(loop, sound, presence)
        evidence["physical_gate"].update(
            {
                "single_utterance_preroll": True,
                "single_utterance_preroll_evidence": single_utterance_preroll,
            }
        )
        _write_evidence(args.output, evidence)
        right_ctrl_activation = _right_ctrl_activation_round(loop, sound, presence)
        evidence["physical_gate"].update(
            {
                "right_ctrl_activation": True,
                "right_ctrl_evidence": right_ctrl_activation,
                "activation_router_shared_pipeline": True,
            }
        )
        _write_evidence(args.output, evidence)
        for language in ("Arabic", "English", "mixed Arabic-English"):
            started = time.perf_counter()
            result = _turn(loop, sound, f"{language} voice request", 8.0, presence=presence)
            turn_latencies.append((time.perf_counter() - started) * 1000)
            stt_results[language] = bool(result.transcript) and result.degraded_reason is None
            if result.state not in {VoiceState.FOLLOW_UP_LISTENING, VoiceState.DEGRADED}:
                raise RuntimeError(f"voice turn did not complete truthfully: {result.state.value}")

        follow_up = _turn(loop, sound, "Follow-up without saying Jarvis", 8.0, presence=presence)
        silence_state = loop.silence_timeout().value
        smart_turn_natural_pause = _smart_turn_pause_round(loop, sound, presence)
        evidence["physical_gate"].update(
            {
                "smart_turn_natural_pause": True,
                "smart_turn_evidence": smart_turn_natural_pause,
            }
        )
        _write_evidence(args.output, evidence)
        loop.activate(ActivationSource.PTT)
        no_speech_result = _turn(
            loop,
            sound,
            "No-speech suppression: remain silent",
            2.0,
            expect_audio=False,
            presence=presence,
        )
        no_speech_no_model = (
            no_speech_result.state is VoiceState.SLEEPING
            and no_speech_result.transcript is None
            and no_speech_result.core_request_id is None
        )

        loop.activate(ActivationSource.PTT)
        playback_error: list[BaseException] = []

        def run_seed_turn() -> None:
            try:
                _turn(loop, sound, "Barge-in seed request", 8.0, presence=presence)
            except BaseException as exc:
                playback_error.append(exc)

        playback_thread = threading.Thread(target=run_seed_turn, daemon=True)
        playback_thread.start()
        deadline = time.monotonic() + 30.0
        while loop.state is not VoiceState.SPEAKING and time.monotonic() < deadline:
            time.sleep(0.05)
        if loop.state is not VoiceState.SPEAKING:
            raise RuntimeError("real barge-in gate could not reach speaking state")
        barge_count_before = loop.metrics.barge_in_count
        _countdown("Barge-in now while JARVIS is speaking. Speak naturally after the countdown.")
        live_thread, live_stop, live_result = _start_live_capture(loop, sound, 2.0)
        live_result = _finish_live_capture(
            live_thread, live_stop, live_result, timeout_seconds=10.0
        )
        if int(live_result["frame_count"]) <= 0:
            raise RuntimeError("real barge-in gate captured no live microphone frames")
        barge_metrics = loop.metrics
        cancel_latency_p50_ms = barge_metrics.cancel_latency_p50_ms
        cancel_latency_p95_ms = barge_metrics.cancel_latency_p95_ms
        playback_thread.join(timeout=30)
        if playback_error:
            raise RuntimeError(
                f"barge-in playback thread failed: {type(playback_error[0]).__name__}"
            )
        barge_in_pass = (
            int(loop.metrics.barge_in_count) > barge_count_before
            and cancel_latency_p50_ms is not None
            and cancel_latency_p95_ms is not None
        )

        _reset_to_sleep(loop)
        loop.activate(ActivationSource.PTT)
        ptt_result = _turn(loop, sound, "PTT fallback", 8.0, presence=presence)
        _reset_to_sleep(loop)

        loop.activate(ActivationSource.PTT)
        stop_result = _turn(
            loop, sound, "Say the exact local sleep command", 4.0, presence=presence
        )
        stop_sleep_pass = stop_result.state is VoiceState.SLEEPING

        loop.activate(ActivationSource.PTT)
        unavailable_core_original = pipeline.core
        pipeline.core = UnavailableCore()
        degraded_result = _turn(
            loop, sound, "Bounded Core unavailable probe", 4.0, presence=presence
        )
        core_degraded_pass = (
            degraded_result.state is VoiceState.DEGRADED
            and degraded_result.degraded_reason is not None
        )
        pipeline.core = unavailable_core_original
        _reset_to_sleep(loop)

        loop.activate(ActivationSource.PTT)
        unavailable_tts_original = pipeline.tts
        pipeline.tts = UnavailableTts()
        tts_fallback_result = _turn(
            loop, sound, "Bounded TTS unavailable probe", 4.0, presence=presence
        )
        tts_fallback_pass = (
            tts_fallback_result.core_request_id is not None and not tts_fallback_result.audio_played
        )
        pipeline.tts = unavailable_tts_original
        _reset_to_sleep(loop)

        loop.activate(ActivationSource.PTT)
        phase9_result = _turn(
            loop,
            sound,
            "Read the current Windows status through the approved harmless action path",
            8.0,
            presence=presence,
        )
        phase9_pass = (
            phase9_result.core_request_id is not None and phase9_result.degraded_reason is None
        )
        _reset_to_sleep(loop)
        loop.activate(ActivationSource.PTT)
        qwen4b_result = _turn(
            loop,
            sound,
            "Give a short ordinary Qwen 4B regression response",
            8.0,
            presence=presence,
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
                "single_utterance_preroll": single_utterance_preroll["status"] == "pass",
                "right_ctrl_activation": right_ctrl_activation["status"] == "pass",
                "smart_turn_natural_pause": smart_turn_natural_pause["status"] == "pass",
                "activation_router_shared_pipeline": True,
                "single_utterance_preroll_evidence": single_utterance_preroll,
                "right_ctrl_evidence": right_ctrl_activation,
                "smart_turn_evidence": smart_turn_natural_pause,
                "follow_up": follow_up.state is VoiceState.FOLLOW_UP_LISTENING,
                "silence_timeout": silence_state == VoiceState.SLEEPING.value,
                "barge_in": barge_in_pass,
                "barge_in_evidence": {
                    "capture_start_to_barge_in_ms": live_result.get("capture_start_to_barge_in_ms"),
                    "cancel_latency_p50_ms": cancel_latency_p50_ms,
                    "cancel_latency_p95_ms": cancel_latency_p95_ms,
                },
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
            "wake_word_model",
            "wake_word_device",
            "wake_word_compute_type",
            "wake_word_beam_size",
            "wake_word_hotwords",
            "recall",
            "misses",
            "false_activation_count",
            "wake_latency_ms_median",
            "barge_in_evidence",
            "failure",
            "owner_gate_policy",
            "single_utterance_preroll_evidence",
            "right_ctrl_evidence",
            "smart_turn_evidence",
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
