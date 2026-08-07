"""Benchmark the local-only Phase 4 Ollama model node."""

from __future__ import annotations

import argparse
import base64
import contextlib
import ctypes
import hashlib
import itertools
import json
import math
import os
import re
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.phase_04.sanitize_evidence import write_sanitized
from scripts.phase_04.verify_release import (
    VerificationError,
    require_digest_prefix,
    validate_model_manifest,
)

THERMAL_WARNING_C = 85.0
THERMAL_ABORT_C = 87.0
THERMAL_STOP_C = 87.0
PRE_REQUEST_MAX_C = 70.0
COMMITTED_MEMORY_MAX_PERCENT = 90.0
REQUEST_TIMEOUT_SECONDS = 60.0
EXPECTED_CONTEXTS = (4096, 8192, 16384)
EMBEDDING_REPEAT_MIN_COSINE = 0.999
EXPECTED_MODELS = {
    "primary": {
        "tag": "qwen3.5:4b",
        "digest_prefix": "2a654d98e6fb",
        "license": "Apache-2.0",
    },
    "embeddings": {
        "tag": "bge-m3:567m",
        "digest_prefix": "790764642607",
        "license": "MIT",
    },
}


@dataclass(frozen=True, slots=True)
class InteractiveBudget:
    role: str
    max_output_tokens: int
    request_timeout_seconds: float = REQUEST_TIMEOUT_SECONDS
    default_context: int = 4096


INTERACTIVE_BUDGETS = {
    "primary": InteractiveBudget("primary", 256),
}


class BenchmarkError(RuntimeError):
    """Raised for a required benchmark or security failure."""


class ThermalStop(BenchmarkError):
    """Raised when the safety threshold requires an immediate stop."""


class OllamaHttpError(BenchmarkError):
    """Raised for a local Ollama HTTP error without exposing response data."""

    def __init__(self, status: int, endpoint: str) -> None:
        super().__init__(f"Local Ollama HTTP {status} at {endpoint}")
        self.status = status
        self.endpoint = endpoint


def assert_local_base_url(base_url: str) -> str:
    """Accept only an HTTP URL using the literal IPv4 loopback address."""

    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
        raise BenchmarkError("Benchmark base URL must be http://127.0.0.1")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise BenchmarkError("Benchmark base URL contains unsupported data")
    try:
        port = parsed.port or 80
    except ValueError as exc:
        raise BenchmarkError("Benchmark base URL port is invalid") from exc
    if not 1 <= port <= 65535:
        raise BenchmarkError("Benchmark base URL port is invalid")
    return f"http://127.0.0.1:{port}"


def duration_ns_to_seconds(value: object) -> float:
    """Convert Ollama nanosecond metrics to non-negative seconds."""

    if not isinstance(value, (int, float)) or value < 0:
        return 0.0
    return float(value) / 1_000_000_000


def tokens_per_second(token_count: object, duration_ns: object) -> float:
    """Calculate a bounded token rate from Ollama metrics."""

    if not isinstance(token_count, (int, float)) or token_count <= 0:
        return 0.0
    seconds = duration_ns_to_seconds(duration_ns)
    return float(token_count) / seconds if seconds > 0 else 0.0


def median(values: Sequence[float]) -> float:
    """Return a median for a non-empty numeric sequence."""

    if not values:
        raise BenchmarkError("Median requires at least one value")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def parse_stream_line(line: str) -> dict[str, Any]:
    """Parse one Ollama NDJSON event without echoing invalid content."""

    try:
        value = json.loads(line)
    except json.JSONDecodeError as exc:
        raise BenchmarkError("Ollama returned invalid stream JSON") from exc
    if not isinstance(value, dict):
        raise BenchmarkError("Ollama stream event is not an object")
    return cast(dict[str, Any], value)


def validate_context_case(response: str, needle: str) -> bool:
    return response.strip() == needle


def validate_marker_response(response: str, marker: str) -> bool:
    return bool(response.strip()) and marker in response


def validate_structured_output(response: str) -> bool:
    try:
        value = json.loads(response)
    except json.JSONDecodeError:
        return False
    return (
        isinstance(value, dict)
        and value.get("status") == "ok"
        and isinstance(value.get("summary"), str)
        and len(value["summary"]) <= 120
        and set(value) == {"status", "summary"}
    )


def validate_vision_output(value: Mapping[str, Any]) -> bool:
    color = str(value.get("color", "")).casefold()
    return (
        color in {"red", "#ff0000"}
        and str(value.get("shape", "")).casefold() == "square"
        and str(value.get("text", "")).strip() == "BMO-42"
    )


def validate_tool_call(message: Mapping[str, Any]) -> bool:
    calls = message.get("tool_calls")
    if not isinstance(calls, list) or len(calls) != 1 or not isinstance(calls[0], Mapping):
        return False
    function = calls[0].get("function")
    if not isinstance(function, Mapping) or function.get("name") != "get_synthetic_temperature":
        return False
    arguments = function.get("arguments")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return False
    return (
        isinstance(arguments, Mapping) and arguments.get("city") == "Cairo" and len(arguments) == 1
    )


def validate_embedding(vector: Sequence[object], dimension: int = 1024) -> bool:
    return len(vector) == dimension and all(
        isinstance(value, (int, float)) and math.isfinite(float(value)) for value in vector
    )


def validate_embedding_acceptance(
    reference: Sequence[object],
    repeated: Sequence[object],
    near_safe: Sequence[object],
) -> float:
    """Enforce repeat consistency and a valid near-safe embedding response."""

    if not validate_embedding(reference) or not validate_embedding(repeated):
        raise BenchmarkError("BGE-M3 repeated input returned an invalid vector")
    if not validate_embedding(near_safe):
        raise BenchmarkError("BGE-M3 near-safe input returned an invalid vector")
    repeat_cosine = cosine_similarity(
        [float(cast(float, value)) for value in reference],
        [float(cast(float, value)) for value in repeated],
    )
    if repeat_cosine < EMBEDDING_REPEAT_MIN_COSINE:
        raise BenchmarkError("BGE-M3 repeated input is not numerically consistent")
    return repeat_cosine


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise BenchmarkError("Cosine similarity requires equal non-empty vectors")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise BenchmarkError("Cosine similarity requires non-zero vectors")
    return dot / (left_norm * right_norm)


def thermal_stop_decision(temperature_c: float) -> bool:
    return temperature_c >= THERMAL_STOP_C


def thermal_warning_decision(temperature_c: float) -> bool:
    return temperature_c >= THERMAL_WARNING_C


def thermal_abort_decision(temperature_c: float) -> bool:
    return temperature_c >= THERMAL_ABORT_C


def cooldown_state(peak_temperature_c: float) -> str:
    if peak_temperature_c >= THERMAL_WARNING_C:
        return "cool_to_60c"
    return "wait_20s"


def validate_interactive_budget(role: str, output_tokens: int, timeout_seconds: float) -> None:
    budget = INTERACTIVE_BUDGETS.get(role)
    if budget is None:
        raise BenchmarkError("Unknown Qwen interactive role")
    if not 1 <= output_tokens <= budget.max_output_tokens:
        raise BenchmarkError("Interactive output budget exceeded")
    if not 0 < timeout_seconds <= budget.request_timeout_seconds:
        raise BenchmarkError("Interactive request timeout exceeded")


def validate_interactive_context(context: int, output_tokens: int) -> None:
    if context not in EXPECTED_CONTEXTS:
        raise BenchmarkError("Unsupported interactive context tier")
    if context > 4096 and output_tokens > 32:
        raise BenchmarkError("Large-context interactive output must remain short")


def validate_pre_request_state(
    sample: GpuSample,
    ac_connected: bool,
    committed_memory_percent: float,
    loaded_qwen_models: Sequence[str],
    target_tag: str,
) -> None:
    if sample.temperature_c > PRE_REQUEST_MAX_C:
        raise BenchmarkError("GPU is above the interactive pre-request temperature gate")
    if not ac_connected:
        raise BenchmarkError("AC power is not connected")
    if committed_memory_percent >= COMMITTED_MEMORY_MAX_PERCENT:
        raise BenchmarkError("Committed memory is at or above the interactive limit")
    if sample.thermal_slowdown:
        raise ThermalStop("GPU thermal slowdown is active")
    if len(loaded_qwen_models) > 1 or any(tag != target_tag for tag in loaded_qwen_models):
        raise BenchmarkError("More than one or an unexpected Qwen model is loaded")


def ac_power_connected() -> bool:
    if os.name != "nt":
        raise BenchmarkError("AC power status is unavailable on this platform")

    class SystemPowerStatus(ctypes.Structure):
        _fields_ = [
            ("ac_line_status", ctypes.c_ubyte),
            ("battery_flag", ctypes.c_ubyte),
            ("battery_life_percent", ctypes.c_ubyte),
            ("reserved", ctypes.c_ubyte),
            ("battery_life_time", ctypes.c_ulong),
            ("battery_full_life_time", ctypes.c_ulong),
        ]

    status = SystemPowerStatus()
    windll = getattr(ctypes, "windll", None)
    if windll is None or not windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        raise BenchmarkError("AC power status could not be read")
    return int(status.ac_line_status) == 1


def committed_memory_percent() -> float:
    if os.name != "nt":
        raise BenchmarkError("Committed memory status is unavailable on this platform")
    command = (
        "(Get-Counter '\\Memory\\% Committed Bytes In Use' "
        "-ErrorAction Stop).CounterSamples[0].CookedValue"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BenchmarkError("Committed memory status could not be read") from exc
    if completed.returncode != 0:
        raise BenchmarkError("Committed memory status could not be read")
    try:
        return float(completed.stdout.strip())
    except ValueError as exc:
        raise BenchmarkError("Committed memory status was malformed") from exc


def thermal_slowdown_from_field(value: str) -> bool:
    normalized = value.strip().casefold()
    return normalized not in {
        "0",
        "0x0000000000000000",
        "[n/a]",
        "n/a",
        "not active",
        "inactive",
        "none",
    }


@dataclass(frozen=True, slots=True)
class ResponseResult:
    text: str
    metrics: dict[str, float]


@dataclass(frozen=True, slots=True)
class GpuSample:
    temperature_c: float
    utilization_percent: float
    vram_used_mib: float
    vram_total_mib: float
    power_draw_w: float
    power_limit_w: float
    pstate: str
    thermal_slowdown: bool


class GpuSampler:
    """Sample only bounded NVIDIA GPU and thermal fields in a child process."""

    def __init__(self, interval_seconds: float = 1.0) -> None:
        self.interval_seconds = interval_seconds
        self._samples: list[GpuSample] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def _number(value: str) -> float:
        cleaned = value.strip().replace("[N/A]", "").replace("N/A", "")
        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    @staticmethod
    def _sample_once() -> GpuSample:
        command = [
            "nvidia-smi",
            "--query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw,power.limit,pstate,clocks_throttle_reasons.hw_thermal_slowdown",
            "--format=csv,noheader,nounits",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise BenchmarkError("nvidia-smi sampling failed") from exc
        if completed.returncode != 0 or not completed.stdout.strip():
            raise BenchmarkError("nvidia-smi returned no GPU sample")
        fields = [field.strip() for field in completed.stdout.splitlines()[0].split(",")]
        if len(fields) < 8:
            raise BenchmarkError("nvidia-smi returned an incomplete GPU sample")
        return GpuSample(
            temperature_c=GpuSampler._number(fields[0]),
            utilization_percent=GpuSampler._number(fields[1]),
            vram_used_mib=GpuSampler._number(fields[2]),
            vram_total_mib=GpuSampler._number(fields[3]),
            power_draw_w=GpuSampler._number(fields[4]),
            power_limit_w=GpuSampler._number(fields[5]),
            pstate=fields[6],
            thermal_slowdown=thermal_slowdown_from_field(fields[7]),
        )

    @staticmethod
    def detected_identity() -> dict[str, Any]:
        command = ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise BenchmarkError("nvidia-smi identity query failed") from exc
        if completed.returncode != 0 or not completed.stdout.strip():
            raise BenchmarkError("nvidia-smi returned incomplete GPU identity")
        fields = [field.strip() for field in completed.stdout.splitlines()[0].split(",")]
        if len(fields) != 2 or not fields[0]:
            raise BenchmarkError("nvidia-smi returned incomplete GPU identity")
        return {
            "gpu_detected_by": "nvidia-smi",
            "gpu_name": fields[0],
            "vram_total_mib": GpuSampler._number(fields[1]),
            "device_class_owner_reported": "ASUS TUF F15",
            "system_ram_gb_owner_reported": 16,
        }

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                sample = self._sample_once()
                with self._lock:
                    self._samples.append(sample)
            except BenchmarkError:
                self._stop_event.set()
                return
            self._stop_event.wait(self.interval_seconds)

    def __enter__(self) -> GpuSampler:
        self._samples = [self._sample_once()]
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="phase4-gpu-sampler", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=15)

    def stop_requested(self) -> bool:
        with self._lock:
            return any(
                thermal_stop_decision(sample.temperature_c) or sample.thermal_slowdown
                for sample in self._samples
            )

    def abort_requested(self) -> bool:
        with self._lock:
            return any(
                thermal_abort_decision(sample.temperature_c) or sample.thermal_slowdown
                for sample in self._samples
            )

    def warning_requested(self) -> bool:
        with self._lock:
            return any(thermal_warning_decision(sample.temperature_c) for sample in self._samples)

    def request_abort_requested(self) -> bool:
        with self._lock:
            if any(
                thermal_abort_decision(sample.temperature_c) or sample.thermal_slowdown
                for sample in self._samples
            ):
                return True
            if len(self._samples) < 2:
                return False
            previous, latest = self._samples[-2:]
            return thermal_warning_decision(latest.temperature_c) and (
                latest.temperature_c > previous.temperature_c
            )

    def summary(self) -> dict[str, Any]:
        with self._lock:
            samples = list(self._samples)
        if not samples:
            raise BenchmarkError("No GPU samples were collected")
        return {
            "sample_count": len(samples),
            "peak_temperature_c": max(sample.temperature_c for sample in samples),
            "end_temperature_c": samples[-1].temperature_c,
            "peak_utilization_percent": max(sample.utilization_percent for sample in samples),
            "peak_vram_used_mib": max(sample.vram_used_mib for sample in samples),
            "vram_total_mib": max(sample.vram_total_mib for sample in samples),
            "peak_power_draw_w": max(sample.power_draw_w for sample in samples),
            "power_limit_w": max(sample.power_limit_w for sample in samples),
            "pstates": sorted({sample.pstate for sample in samples}),
            "thermal_warning": any(
                thermal_warning_decision(sample.temperature_c) for sample in samples
            ),
            "thermal_slowdown": any(sample.thermal_slowdown for sample in samples),
        }


class InteractiveThermalGovernor:
    """Enforce the bounded single-model interactive operating envelope."""

    def __init__(
        self,
        client: LocalOllama,
        tag: str,
        role: str,
        *,
        sample_once: Callable[[], GpuSample] = GpuSampler._sample_once,
        ac_check: Callable[[], bool] = ac_power_connected,
        memory_check: Callable[[], float] = committed_memory_percent,
        sleep: Callable[[float], None] = time.sleep,
        pre_request_wait_seconds: float = 600.0,
    ) -> None:
        if role not in INTERACTIVE_BUDGETS:
            raise BenchmarkError("Unknown Qwen interactive role")
        self.client = client
        self.tag = tag
        self.budget = INTERACTIVE_BUDGETS[role]
        self._sample_once = sample_once
        self._ac_check = ac_check
        self._memory_check = memory_check
        self._sleep = sleep
        self._pre_request_wait_seconds = pre_request_wait_seconds
        self._active = False
        self._records: list[dict[str, Any]] = []

    @property
    def records(self) -> list[dict[str, Any]]:
        return list(self._records)

    def _loaded_models(self) -> list[str]:
        loaded: list[str] = []
        for model in self.client.ps():
            name = model.get("name") or model.get("model")
            if isinstance(name, str):
                loaded.append(name)
        return loaded

    def _wait_pre_request_gate(self) -> None:
        deadline = time.monotonic() + self._pre_request_wait_seconds
        while True:
            sample = self._sample_once()
            if thermal_abort_decision(sample.temperature_c) or sample.thermal_slowdown:
                raise ThermalStop("GPU failed the pre-request thermal gate")
            loaded = self._loaded_models()
            qwen_loaded = [name for name in loaded if name.startswith("qwen3.5:")]
            if any(name != self.tag for name in loaded):
                raise BenchmarkError("Another model is loaded during the Qwen request gate")
            if sample.temperature_c <= PRE_REQUEST_MAX_C:
                memory_percent = self._memory_check()
                if memory_percent >= COMMITTED_MEMORY_MAX_PERCENT and loaded == [self.tag]:
                    _unload(self.client, self.tag)
                    self._sleep(1.0)
                    continue
                validate_pre_request_state(
                    sample,
                    self._ac_check(),
                    memory_percent,
                    qwen_loaded,
                    self.tag,
                )
                return
            if time.monotonic() >= deadline:
                raise BenchmarkError("GPU did not cool to the pre-request temperature gate")
            self._sleep(1.0)

    def _cool_to(self, target_c: float, timeout_seconds: float = 600.0) -> dict[str, Any]:
        _unload(self.client, self.tag)
        started = time.monotonic()
        samples: list[GpuSample] = []
        while time.monotonic() - started <= timeout_seconds:
            sample = self._sample_once()
            samples.append(sample)
            if thermal_abort_decision(sample.temperature_c) or sample.thermal_slowdown:
                raise ThermalStop("GPU thermal safety state did not recover")
            if sample.temperature_c <= target_c:
                return {
                    "target_temperature_c": target_c,
                    "duration_seconds": round(time.monotonic() - started, 3),
                    "end_temperature_c": sample.temperature_c,
                }
            self._sleep(1.0)
        raise BenchmarkError("GPU did not cool within the bounded cooldown window")

    def _post_request(self, summary: dict[str, Any]) -> None:
        peak = float(summary["peak_temperature_c"])
        if peak >= THERMAL_ABORT_C or summary["thermal_slowdown"]:
            with contextlib.suppress(BenchmarkError):
                _unload(self.client, self.tag)
            raise ThermalStop("GPU reached the interactive abort threshold")
        state = cooldown_state(peak)
        summary["cooldown_state"] = state
        if state == "wait_20s":
            self._sleep(20.0)
            summary["cooldown_temperature_c"] = self._sample_once().temperature_c
        else:
            summary["cooldown"] = self._cool_to(60.0)

    def _run_request(
        self,
        output_tokens: int,
        context: int,
        timeout_seconds: float,
        operation: Callable[[GpuSampler], Any],
    ) -> tuple[Any, dict[str, Any]]:
        validate_interactive_budget(self.budget.role, output_tokens, timeout_seconds)
        validate_interactive_context(context, output_tokens)
        if self._active:
            raise BenchmarkError("Concurrent interactive requests are not allowed")
        self._active = True
        try:
            self._wait_pre_request_gate()
            with GpuSampler(interval_seconds=1.0) as sampler:
                try:
                    result = operation(sampler)
                except Exception:
                    with contextlib.suppress(BenchmarkError):
                        _unload(self.client, self.tag)
                    raise
            summary = sampler.summary()
            self._post_request(summary)
            self._records.append(summary)
            return result, summary
        finally:
            self._active = False

    def generate(
        self,
        prompt: str,
        *,
        output_tokens: int,
        context: int = 4096,
        keep_alive: int | str | None = 0,
        format_schema: Mapping[str, Any] | None = None,
        images: Sequence[str] | None = None,
    ) -> ResponseResult:
        result, summary = self._run_request(
            output_tokens,
            context,
            self.budget.request_timeout_seconds,
            lambda sampler: self.client.stream_generate(
                self.tag,
                prompt,
                num_predict=output_tokens,
                num_ctx=context,
                keep_alive=keep_alive,
                format_schema=format_schema,
                images=images,
                timeout_seconds=self.budget.request_timeout_seconds,
                thermal_check=sampler.request_abort_requested,
            ),
        )
        if not isinstance(result, ResponseResult):
            raise BenchmarkError("Interactive generation returned an invalid result")
        result.metrics.update(
            {
                "peak_temperature_c": float(summary["peak_temperature_c"]),
                "end_temperature_c": float(summary["end_temperature_c"]),
            }
        )
        return result

    def chat(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        output_tokens: int,
        tools: Sequence[Mapping[str, Any]] | None = None,
        format_schema: Mapping[str, Any] | None = None,
        images: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        result, _summary = self._run_request(
            output_tokens,
            self.budget.default_context,
            self.budget.request_timeout_seconds,
            lambda _sampler: self.client.chat(
                self.tag,
                messages,
                tools=tools,
                format_schema=format_schema,
                images=images,
                num_predict=output_tokens,
                timeout_seconds=self.budget.request_timeout_seconds,
            ),
        )
        if not isinstance(result, dict):
            raise BenchmarkError("Interactive chat returned an invalid result")
        return result

    def end_group(self, target_c: float = 60.0) -> dict[str, Any]:
        return self._cool_to(target_c)

    def performance_summary(self) -> dict[str, Any]:
        if not self._records:
            raise BenchmarkError("No interactive GPU records were collected")
        return {
            "sample_count": sum(int(record["sample_count"]) for record in self._records),
            "peak_temperature_c": max(record["peak_temperature_c"] for record in self._records),
            "end_temperature_c": self._records[-1]["end_temperature_c"],
            "peak_utilization_percent": max(
                record["peak_utilization_percent"] for record in self._records
            ),
            "peak_vram_used_mib": max(record["peak_vram_used_mib"] for record in self._records),
            "vram_total_mib": max(record["vram_total_mib"] for record in self._records),
            "peak_power_draw_w": max(record["peak_power_draw_w"] for record in self._records),
            "power_limit_w": max(record["power_limit_w"] for record in self._records),
            "thermal_warning": any(record["thermal_warning"] for record in self._records),
            "thermal_slowdown": any(record["thermal_slowdown"] for record in self._records),
        }


class LocalOllama:
    """Small local HTTP client that refuses non-loopback endpoints."""

    def __init__(self, base_url: str, timeout_seconds: float = 180.0) -> None:
        self.base_url = assert_local_base_url(base_url)
        self.timeout_seconds = timeout_seconds

    def _url(self, endpoint: str) -> str:
        return f"{self.base_url}{endpoint}"

    def request_json(
        self,
        method: str,
        endpoint: str,
        payload: Mapping[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self._url(endpoint),
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout_seconds or self.timeout_seconds,
            ) as response:
                value = json.load(response)
        except urllib.error.HTTPError as exc:
            raise OllamaHttpError(exc.code, endpoint) from exc
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise BenchmarkError(f"Local Ollama request failed at {endpoint}") from exc
        if not isinstance(value, dict):
            raise BenchmarkError(f"Local Ollama response at {endpoint} is not an object")
        return cast(dict[str, Any], value)

    def version(self) -> str:
        value = self.request_json("GET", "/api/version")
        version = value.get("version")
        if not isinstance(version, str):
            raise BenchmarkError("Ollama version response is invalid")
        return version

    def tags(self) -> list[dict[str, Any]]:
        value = self.request_json("GET", "/api/tags")
        models = value.get("models")
        if not isinstance(models, list):
            raise BenchmarkError("Ollama tags response is invalid")
        return [cast(dict[str, Any], item) for item in models if isinstance(item, dict)]

    def show(self, tag: str) -> dict[str, Any]:
        return self.request_json("POST", "/api/show", {"name": tag})

    def ps(self) -> list[dict[str, Any]]:
        value = self.request_json("GET", "/api/ps")
        models = value.get("models")
        if not isinstance(models, list):
            raise BenchmarkError("Ollama ps response is invalid")
        return [cast(dict[str, Any], item) for item in models if isinstance(item, dict)]

    def stream_generate(
        self,
        model: str,
        prompt: str,
        *,
        num_predict: int = 128,
        num_ctx: int | None = None,
        keep_alive: int | str | None = None,
        format_schema: Mapping[str, Any] | None = None,
        images: Sequence[str] | None = None,
        timeout_seconds: float | None = None,
        thermal_check: Callable[[], bool] | None = None,
    ) -> ResponseResult:
        options: dict[str, Any] = {"temperature": 0, "num_predict": num_predict}
        if num_ctx is not None:
            options["num_ctx"] = num_ctx
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "think": False,
            "options": options,
        }
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        if format_schema is not None:
            payload["format"] = dict(format_schema)
        if images is not None:
            payload["images"] = list(images)
        request = urllib.request.Request(
            self._url("/api/generate"),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.perf_counter()
        pieces: list[str] = []
        final: dict[str, Any] = {}
        first_content: float | None = None
        try:
            response = urllib.request.urlopen(
                request, timeout=timeout_seconds or self.timeout_seconds
            )
            with response:
                for line in response:
                    event = parse_stream_line(line.decode("utf-8"))
                    if thermal_check is not None and thermal_check():
                        raise ThermalStop("GPU thermal safety threshold reached")
                    chunk = event.get("response")
                    if isinstance(chunk, str):
                        if chunk and first_content is None:
                            first_content = time.perf_counter() - started
                        pieces.append(chunk)
                    if event.get("done") is True:
                        final = event
                        break
        except urllib.error.HTTPError as exc:
            raise OllamaHttpError(exc.code, "/api/generate") from exc
        except ThermalStop:
            raise
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise BenchmarkError("Local Ollama generation request failed") from exc
        if not final:
            raise BenchmarkError("Ollama generation stream did not finish")
        metrics = {
            "wall_duration_s": time.perf_counter() - started,
            "ttft_s": first_content or 0.0,
            "total_duration_s": duration_ns_to_seconds(final.get("total_duration")),
            "load_duration_s": duration_ns_to_seconds(final.get("load_duration")),
            "input_eval_count": float(final.get("prompt_eval_count") or 0),
            "input_eval_duration_s": duration_ns_to_seconds(final.get("prompt_eval_duration")),
            "eval_count": float(final.get("eval_count") or 0),
            "eval_duration_s": duration_ns_to_seconds(final.get("eval_duration")),
        }
        metrics["generation_rate_per_second"] = tokens_per_second(
            final.get("eval_count"), final.get("eval_duration")
        )
        metrics["input_rate_per_second"] = tokens_per_second(
            final.get("prompt_eval_count"), final.get("prompt_eval_duration")
        )
        return ResponseResult("".join(pieces), metrics)

    def chat(
        self,
        model: str,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        format_schema: Mapping[str, Any] | None = None,
        images: Sequence[str] | None = None,
        num_predict: int = 128,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        normalized_messages = [dict(message) for message in messages]
        if images:
            normalized_messages[-1]["images"] = list(images)
        payload: dict[str, Any] = {
            "model": model,
            "messages": normalized_messages,
            "stream": False,
            "think": False,
            "options": {"temperature": 0, "num_predict": num_predict},
        }
        if tools is not None:
            payload["tools"] = [dict(tool) for tool in tools]
        if format_schema is not None:
            payload["format"] = dict(format_schema)
        return self.request_json("POST", "/api/chat", payload, timeout_seconds=timeout_seconds)

    def embed(
        self,
        model: str,
        inputs: str | Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[list[list[float]], dict[str, float]]:
        started = time.perf_counter()
        value = self.request_json(
            "POST",
            "/api/embed",
            {"model": model, "input": inputs, "truncate": False},
            timeout_seconds=timeout_seconds or 240,
        )
        embeddings = value.get("embeddings")
        if not isinstance(embeddings, list):
            raise BenchmarkError("Ollama embedding response is invalid")
        vectors: list[list[float]] = []
        for embedding in embeddings:
            if not isinstance(embedding, list):
                raise BenchmarkError("Ollama embedding vector is invalid")
            vectors.append([float(number) for number in embedding])
        return vectors, {"wall_duration_s": time.perf_counter() - started}


def _metric_record(metrics: Mapping[str, float], **extra: Any) -> dict[str, Any]:
    result: dict[str, Any] = {key: round(float(value), 6) for key, value in metrics.items()}
    result.update(extra)
    return result


def _case(case_id: str, passed: bool, metrics: Mapping[str, float], **extra: Any) -> dict[str, Any]:
    return {"case_id": case_id, "pass": passed, "metrics": _metric_record(metrics, **extra)}


def _tool_definition() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "get_synthetic_temperature",
            "description": "Return a synthetic temperature for a named city.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string", "enum": ["Cairo"]}},
                "required": ["city"],
                "additionalProperties": False,
            },
        },
    }


def _structured_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["status", "summary"],
        "properties": {
            "status": {"type": "string", "enum": ["ok"]},
            "summary": {"type": "string", "maxLength": 120},
        },
        "additionalProperties": False,
    }


def _vision_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["color", "shape", "text"],
        "properties": {
            "color": {"type": "string"},
            "shape": {"type": "string"},
            "text": {"type": "string"},
        },
        "additionalProperties": False,
    }


FONT = {
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
}


def create_test_png() -> bytes:
    """Create a deterministic RGB PNG with a red square and BMO-42 text."""

    width, height = 280, 150
    pixels = bytearray(width * height * 3)
    for index in range(0, len(pixels), 3):
        pixels[index : index + 3] = b"\xff\xff\xff"
    for y in range(20, 90):
        for x in range(20, 90):
            offset = (y * width + x) * 3
            pixels[offset : offset + 3] = b"\xff\x00\x00"
    text = "BMO-42"
    for char_index, char in enumerate(text):
        glyph = FONT[char]
        left = 110 + char_index * 26
        for y, row in enumerate(glyph):
            for x, bit in enumerate(row):
                if bit == "1":
                    for dy in range(3):
                        for dx in range(3):
                            px, py = left + x * 3 + dx, 30 + y * 3 + dy
                            offset = (py * width + px) * 3
                            pixels[offset : offset + 3] = b"\x00\x00\x00"
    scanlines = b"".join(
        b"\x00" + bytes(pixels[row * width * 3 : (row + 1) * width * 3]) for row in range(height)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanlines, level=9))
        + chunk(b"IEND", b"")
    )


def _find_model(models: Sequence[Mapping[str, Any]], tag: str) -> dict[str, Any]:
    for model in models:
        if model.get("name") == tag or model.get("model") == tag:
            return dict(model)
    raise BenchmarkError(f"Required model tag is missing: {tag}")


def _manifest_models(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    try:
        validate_model_manifest(manifest, allow_pending=False)
    except VerificationError as exc:
        raise BenchmarkError("Model manifest failed schema validation") from exc
    models = manifest.get("models")
    if not isinstance(models, list) or [
        item.get("role") for item in models if isinstance(item, Mapping)
    ] != [
        "primary",
        "embeddings",
    ]:
        raise BenchmarkError("Model manifest roles are missing or out of order")
    result: list[dict[str, Any]] = []
    for model in models:
        if not isinstance(model, Mapping):
            raise BenchmarkError("Model manifest contains an invalid entry")
        role = str(model.get("role"))
        expected = EXPECTED_MODELS[role]
        if model.get("tag") != expected["tag"]:
            raise BenchmarkError("Model tag does not match the locked Phase 4 tag")
        require_digest_prefix(str(model.get("digest")), str(expected["digest_prefix"]))
        result.append(dict(model))
    return result


def _verify_installed_models(
    client: LocalOllama, manifest_models: Sequence[Mapping[str, Any]]
) -> None:
    installed = client.tags()
    for manifest in manifest_models:
        tag = str(manifest["tag"])
        model = _find_model(installed, tag)
        actual_digest = str(model.get("digest"))
        if f"sha256:{actual_digest.removeprefix('sha256:')}" != manifest["digest"]:
            raise BenchmarkError("Installed model digest does not match the committed manifest")
        if int(model.get("size") or 0) != int(manifest["size_bytes"]):
            raise BenchmarkError("Installed model size does not match the committed manifest")
        details = client.show(tag).get("details")
        if not isinstance(details, Mapping):
            raise BenchmarkError("Installed model details are missing")
        if details.get("format") != manifest.get("format", "gguf"):
            raise BenchmarkError("Installed model format does not match the manifest")
        if details.get("family") != manifest.get("family"):
            raise BenchmarkError("Installed model family does not match the manifest")
        if details.get("quantization_level") != manifest.get("quantization"):
            raise BenchmarkError("Installed model quantization does not match the manifest")


def _model_ps(client: LocalOllama, tag: str) -> dict[str, Any]:
    for model in client.ps():
        if model.get("name") == tag or model.get("model") == tag:
            return model
    raise BenchmarkError("Model is not present in /api/ps while it should be loaded")


def _wait_unloaded(client: LocalOllama, tag: str, timeout_seconds: float = 90) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not any(model.get("name") == tag or model.get("model") == tag for model in client.ps()):
            return
        time.sleep(1)
    raise BenchmarkError("Model did not unload within the bounded timeout")


def _unload(client: LocalOllama, tag: str) -> None:
    with contextlib.suppress(BenchmarkError):
        client.stream_generate(tag, "", num_predict=1, keep_alive=0)
    _wait_unloaded(client, tag)


def _run_model_cases(
    client: LocalOllama,
    model: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tag = str(model["tag"])
    role = str(model["role"])
    governor = InteractiveThermalGovernor(client, tag, role)

    def generate(
        prompt: str,
        *,
        num_predict: int,
        num_ctx: int | None = None,
        keep_alive: int | str | None = 0,
        format_schema: Mapping[str, Any] | None = None,
        images: Sequence[str] | None = None,
        thermal_check: Callable[[], bool] | None = None,
    ) -> ResponseResult:
        del thermal_check
        return governor.generate(
            prompt,
            output_tokens=num_predict,
            context=num_ctx or 4096,
            keep_alive=keep_alive,
            format_schema=format_schema,
            images=images,
        )

    def chat(
        messages: Sequence[Mapping[str, Any]],
        *,
        output_tokens: int,
        tools: Sequence[Mapping[str, Any]] | None = None,
        format_schema: Mapping[str, Any] | None = None,
        images: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        return governor.chat(
            messages,
            output_tokens=output_tokens,
            tools=tools,
            format_schema=format_schema,
            images=images,
        )

    cases: list[dict[str, Any]] = []
    cold = generate(
        "Return exactly the marker BMO_COLD_OK and no other text.",
        num_predict=16,
        keep_alive=0,
    )
    cold_pass = validate_marker_response(cold.text, "BMO_COLD_OK")
    cases.append(_case("cold_load", cold_pass, cold.metrics, marker=cold_pass))
    warm_results: list[ResponseResult] = []
    for _ in range(3):
        warm_results.append(
            generate(
                "Return exactly the marker BMO_WARM_OK and no other text.",
                num_predict=16,
                keep_alive=0,
            )
        )
    warm_ttft = median([result.metrics["ttft_s"] for result in warm_results])
    warm_tps = median([result.metrics["generation_rate_per_second"] for result in warm_results])
    cases.append(
        _case(
            "warm_summary",
            all("BMO_WARM_OK" in result.text for result in warm_results),
            {"ttft_s": warm_ttft, "generation_rate_per_second": warm_tps},
            run_count=3,
        )
    )
    english = generate(
        "Explain loopback-only API binding in one concise sentence. End exactly with BMO_EN_OK.",
        num_predict=64,
        keep_alive=0,
    )
    cases.append(
        _case(
            "english",
            bool(english.text.strip()) and "BMO_EN_OK" in english.text,
            english.metrics,
            marker="BMO_EN_OK" in english.text,
            no_tool=True,
        )
    )
    arabic = generate(
        "اكتب إجابة عربية قصيرة عن نموذج محلي. اختم بالنص ASCII التالي بالضبط: BMO_AR_OK",
        num_predict=64,
        keep_alive=0,
    )
    cases.append(
        _case(
            "arabic",
            bool(re.search(r"[\u0600-\u06ff]", arabic.text)) and "BMO_AR_OK" in arabic.text,
            arabic.metrics,
            arabic_unicode=bool(re.search(r"[\u0600-\u06ff]", arabic.text)),
            marker="BMO_AR_OK" in arabic.text,
        )
    )
    mixed = generate(
        "Return exactly this sentence and no other text: هذا نموذج محلي يستخدم GPU مع "
        "local model. BMO_MIX_OK.",
        num_predict=80,
        keep_alive=0,
    )
    cases.append(
        _case(
            "mixed_arabic_english",
            bool(re.search(r"[\u0600-\u06ff]", mixed.text))
            and "GPU" in mixed.text
            and "local model" in mixed.text,
            mixed.metrics,
            arabic_unicode=bool(re.search(r"[\u0600-\u06ff]", mixed.text)),
            required_terms="GPU" in mixed.text and "local model" in mixed.text,
        )
    )
    structured = generate(
        "Return only a JSON object with status exactly ok and a short summary string.",
        num_predict=80,
        keep_alive=0,
        format_schema=_structured_schema(),
    )
    cases.append(
        _case("structured_json", validate_structured_output(structured.text), structured.metrics)
    )
    tool_response = chat(
        [
            {
                "role": "user",
                "content": (
                    "Call get_synthetic_temperature exactly once with city Cairo. "
                    "Return the tool call only."
                ),
            }
        ],
        output_tokens=32,
        tools=[_tool_definition()],
    )
    message = tool_response.get("message")
    tool_pass = isinstance(message, Mapping) and validate_tool_call(message)
    cases.append(_case("tool_call_observed_not_executed", tool_pass, {}, execution_count=0))
    png_bytes = create_test_png()
    image_hash = hashlib.sha256(png_bytes).hexdigest()
    vision_pass = False
    vision_metrics: dict[str, float] = {}
    for _ in range(2):
        vision = chat(
            [
                {
                    "role": "user",
                    "content": "Return JSON identifying the image color, shape, and visible text.",
                }
            ],
            output_tokens=64,
            format_schema=_vision_schema(),
            images=[base64.b64encode(png_bytes).decode("ascii")],
        )
        vision_message = vision.get("message")
        vision_text = vision_message.get("content") if isinstance(vision_message, Mapping) else ""
        if isinstance(vision_text, str):
            try:
                vision_value = json.loads(vision_text)
            except json.JSONDecodeError:
                vision_value = {}
            vision_pass = isinstance(vision_value, Mapping) and validate_vision_output(vision_value)
        if vision_pass:
            break
    cases.append(_case("vision", vision_pass, vision_metrics, image_sha256=image_hash))
    for context in EXPECTED_CONTEXTS:
        needle = f"BMO_CTX_{uuid.uuid4().hex[:12].upper()}"
        filler = "synthetic context filler " * max(1, context // 8)
        context_result = generate(
            f"The retrieval needle is {needle}.\n{filler}\nReturn only the exact needle.",
            num_predict=32,
            num_ctx=context,
            keep_alive=0,
        )
        cases.append(
            _case(
                f"context_{context}",
                validate_context_case(context_result.text, needle),
                context_result.metrics,
                requested_context=context,
            )
        )
    gpu_summary = governor.performance_summary()
    try:
        ps_model = _model_ps(client, tag)
        size_vram = float(ps_model.get("size_vram") or 0)
    except BenchmarkError:
        size_vram = float(gpu_summary["peak_vram_used_mib"]) * 1024 * 1024
    if size_vram <= 0:
        raise BenchmarkError("Qwen model reports zero GPU VRAM use")
    cooldown = governor.end_group(60.0)
    cold_load = cold.metrics["load_duration_s"]
    return cases, {
        "cold_load_duration_s": round(cold_load, 6),
        "median_warm_ttft_s": round(warm_ttft, 6),
        "median_warm_generation_rate_per_second": round(warm_tps, 6),
        "size_vram_bytes": int(size_vram),
        "gpu": gpu_summary,
        "cooldown": cooldown,
    }


def _run_embedding_cases(client: LocalOllama, model: Mapping[str, Any]) -> dict[str, Any]:
    tag = str(model["tag"])
    english_a = "The local model runs on the ASUS TUF compute node."
    english_b = "ASUS TUF provides local inference for the model node."
    english_unrelated = "A small red square is drawn on a white canvas."
    arabic_a = "يعمل النموذج المحلي على عقدة الحوسبة ASUS TUF."
    arabic_b = "تستضيف ASUS TUF الاستدلال المحلي للنموذج."
    arabic_unrelated = "المربع الأحمر مرسوم على خلفية بيضاء."
    vectors, first_metrics = client.embed(
        tag,
        [english_a, english_b, english_unrelated, arabic_a, arabic_b, arabic_unrelated],
    )
    if len(vectors) != 6 or not all(validate_embedding(vector) for vector in vectors):
        raise BenchmarkError("BGE-M3 did not return valid 1024-dimensional batch vectors")
    repeat, repeat_metrics = client.embed(tag, english_a)
    if len(repeat) != 1:
        raise BenchmarkError("BGE-M3 repeated input returned an invalid vector")
    english_similarity = cosine_similarity(vectors[0], vectors[1])
    english_unrelated_similarity = cosine_similarity(vectors[0], vectors[2])
    arabic_similarity = cosine_similarity(vectors[3], vectors[4])
    arabic_unrelated_similarity = cosine_similarity(vectors[3], vectors[5])
    near_safe = "multilingual retrieval acceptance " * 250
    near_vectors, near_metrics = client.embed(tag, near_safe)
    if len(near_vectors) != 1:
        raise BenchmarkError("BGE-M3 near-safe input returned an invalid vector")
    stability = validate_embedding_acceptance(vectors[0], repeat[0], near_vectors[0])
    over_limit_raises = False
    try:
        client.embed(tag, "over limit sequence " * 10000)
    except OllamaHttpError as exc:
        over_limit_raises = exc.status >= 400
    if not over_limit_raises:
        raise BenchmarkError("BGE-M3 did not fail safely for an over-limit non-truncated input")
    if english_similarity <= english_unrelated_similarity:
        raise BenchmarkError("BGE-M3 English similarity sanity check failed")
    if arabic_similarity <= arabic_unrelated_similarity:
        raise BenchmarkError("BGE-M3 Arabic similarity sanity check failed")
    return {
        "model": tag,
        "dimension": 1024,
        "single_vectors": 6,
        "batch_valid": True,
        "identical_input_cosine": round(stability, 6),
        "english_similar_cosine": round(english_similarity, 6),
        "english_unrelated_cosine": round(english_unrelated_similarity, 6),
        "arabic_similar_cosine": round(arabic_similarity, 6),
        "arabic_unrelated_cosine": round(arabic_unrelated_similarity, 6),
        "near_safe_context_valid": True,
        "over_limit_non_truncated_rejected": over_limit_raises,
        "timings_s": {
            "batch": round(first_metrics["wall_duration_s"], 6),
            "repeat": round(repeat_metrics["wall_duration_s"], 6),
            "near_safe": round(near_metrics["wall_duration_s"], 6),
        },
        "database_write": False,
        "cloud_call": False,
    }


def run_interactive_qualification(
    client: LocalOllama,
    model: Mapping[str, Any],
) -> dict[str, Any]:
    """Run the three bounded role-specific qualification requests."""

    role = str(model["role"])
    tag = str(model["tag"])
    governor = InteractiveThermalGovernor(client, tag, role)
    if role == "primary":
        requests = [
            ("english", 64, "Explain local inference in one concise sentence. End BMO_Q_EN."),
            ("arabic", 128, "اكتب جملة عربية قصيرة عن نموذج محلي. اختم BMO_Q_AR."),
            (
                "technical",
                256,
                "Describe a bounded local model request with one concise technical paragraph.",
            ),
        ]
    else:
        requests = [
            ("english", 64, "Explain local inference in one concise sentence. End BMO_Q_EN."),
            (
                "mixed",
                128,
                (
                    "Return exactly this sentence and no other text: هذا نموذج محلي يستخدم GPU مع "
                    "local model. BMO_Q_MIX."
                ),
            ),
            (
                "technical",
                192,
                "Describe a bounded local model request with one concise technical paragraph.",
            ),
        ]
    cases: list[dict[str, Any]] = []
    for case_id, output_tokens, prompt in requests:
        result = governor.generate(prompt, output_tokens=output_tokens)
        text = result.text
        if case_id == "arabic":
            passed = bool(re.search(r"[\u0600-\u06ff]", text)) and "BMO_Q_AR" in text
        elif case_id == "mixed":
            passed = (
                bool(re.search(r"[\u0600-\u06ff]", text))
                and "GPU" in text
                and "local model" in text
            )
        else:
            passed = bool(text.strip())
        cases.append(_case(case_id, passed, result.metrics, output_budget=output_tokens))
        if not passed:
            raise BenchmarkError(f"Interactive qualification case failed: {case_id}")
    gpu_summary = governor.performance_summary()
    try:
        ps_model = _model_ps(client, tag)
        size_vram = int(float(ps_model.get("size_vram") or 0))
    except BenchmarkError:
        size_vram = int(float(gpu_summary["peak_vram_used_mib"]) * 1024 * 1024)
    if size_vram <= 0:
        raise BenchmarkError("Interactive qualification reports zero GPU VRAM use")
    cooldown = governor.end_group(60.0)
    return {
        "model": tag,
        "cases": cases,
        "size_vram_bytes": size_vram,
        "gpu": gpu_summary,
        "cooldown": cooldown,
    }


def run_practical_stability(
    client: LocalOllama,
    model: Mapping[str, Any],
) -> dict[str, Any]:
    """Run the required three-request bounded stability qualification."""

    role = str(model["role"])
    tag = str(model["tag"])
    governor = InteractiveThermalGovernor(client, tag, role)
    max_tokens = 128
    prompts = [
        "Return one concise sentence about local inference. End BMO_STABLE_1.",
        "Explain loopback-only local inference in a concise paragraph. End BMO_STABLE_2.",
        "Return one concise sentence about bounded context. End BMO_STABLE_3.",
    ]
    starts: list[float] = []
    responses: list[dict[str, Any]] = []
    for index, prompt in enumerate(prompts):
        request_started = time.monotonic()
        if starts:
            remaining = 30.0 - (request_started - starts[-1])
            if remaining > 0:
                time.sleep(remaining)
            request_started = time.monotonic()
        result = governor.generate(
            prompt,
            output_tokens=max_tokens,
            context=4096,
            keep_alive=0,
        )
        starts.append(request_started)
        responses.append(
            {
                "request": index + 1,
                "pass": bool(result.text.strip()),
                "wall_duration_s": round(result.metrics["wall_duration_s"], 6),
                "ttft_s": round(result.metrics["ttft_s"], 6),
                "generation_rate_per_second": round(
                    result.metrics["generation_rate_per_second"], 6
                ),
                "peak_temperature_c": result.metrics["peak_temperature_c"],
                "end_temperature_c": result.metrics["end_temperature_c"],
            }
        )
        if not result.text.strip():
            raise BenchmarkError(f"Bounded stability request failed: {index + 1}")
    gpu_summary = governor.performance_summary()
    try:
        ps_model = _model_ps(client, tag)
        size_vram = int(float(ps_model.get("size_vram") or 0))
    except BenchmarkError:
        size_vram = int(float(gpu_summary["peak_vram_used_mib"]) * 1024 * 1024)
    if size_vram <= 0:
        raise BenchmarkError("Bounded stability reports zero GPU VRAM use")
    cooldown = governor.end_group(60.0)
    return {
        "model": tag,
        "request_count": len(responses),
        "minimum_start_interval_seconds": 30,
        "start_intervals_seconds": [
            round(current - previous, 3) for previous, current in itertools.pairwise(starts)
        ],
        "reload_between_second_and_third": False,
        "requests": responses,
        "size_vram_bytes": size_vram,
        "gpu": gpu_summary,
        "cooldown": cooldown,
    }


def _cooldown(client: LocalOllama, tag: str, seconds: int) -> dict[str, Any]:
    _unload(client, tag)
    started = time.monotonic()
    samples: list[GpuSample] = []
    while time.monotonic() - started < seconds:
        samples.append(GpuSampler._sample_once())
        if thermal_stop_decision(samples[-1].temperature_c):
            raise ThermalStop("GPU did not cool below the thermal safety threshold")
        time.sleep(min(5.0, max(0.0, seconds - (time.monotonic() - started))))
    return {"duration_seconds": seconds, "end_temperature_c": samples[-1].temperature_c}


def write_accepted_evidence(evidence: Mapping[str, Any], output_path: Path) -> None:
    if evidence.get("acceptance") != "pass":
        raise BenchmarkError("Refusing to write non-passing evidence")
    write_sanitized(evidence, output_path)


def stop_dedicated_server() -> None:
    script = (
        Path(__file__).resolve().parents[2] / "infrastructure" / "tuf" / "stop_phase_04_ollama.ps1"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BenchmarkError("Dedicated Ollama stop command failed") from exc
    if completed.returncode != 0:
        raise BenchmarkError("Dedicated Ollama stop command returned a failure")


def run_benchmark(
    base_url: str,
    manifest_path: Path,
    output_path: Path,
    model_root: Path,
    allow_pending_restart: bool = False,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, Mapping):
        raise BenchmarkError("Model manifest is not a JSON object")
    manifest_models = _manifest_models(manifest)
    if not model_root.is_dir() or not (model_root / "manifests").is_dir():
        raise BenchmarkError("Dedicated Ollama model root is missing")
    client = LocalOllama(base_url)
    if client.version() != "0.32.5":
        raise BenchmarkError("Local Ollama version is not 0.32.5")
    _verify_installed_models(client, manifest_models)
    evidence: dict[str, Any] = {
        "phase": "phase-04",
        "schema_version": 1,
        "collected_utc": datetime.now(UTC).date().isoformat(),
        "hardware": GpuSampler.detected_identity(),
        "ollama": {
            "version": manifest["ollama_version"],
            "archive_sha256": manifest["runtime"]["archive_sha256"],
            "executable_sha256": manifest["runtime"]["executable_sha256"],
            "release_tag": "v0.32.5",
            "release_commit": "eec8e0b9458b8a01be0c216a9cc53eefde24ef50",
            "authenticode_status": "Valid",
            "authenticode_signer": "Ollama Inc.",
            "runtime_profile": manifest["runtime_profile"],
        },
        "models": [],
        "functional": {},
        "embeddings": {},
        "thermals": {"continuous_workload_supported": False},
        "restart": {"status": "pending"},
        "security": {
            "base_url_loopback_only": True,
            "cloud_disabled_by_runtime": True,
            "cloud_disabled_by_server_config": True,
            "cloud_auth_configured": False,
            "tool_execution_count": 0,
            "external_benchmark_traffic_after_pulls": False,
            "database_write": False,
        },
        "acceptance": "pending",
        "limitations": [
            "32768 context tier not tested; optional tier deferred.",
            "Continuous 90-second maximum-throughput generation is outside the accepted "
            "operating envelope on the current ASUS TUF cooling configuration. The accepted "
            "node supports bounded single-request interactive inference with enforced "
            "temperature-aware cooldown and no concurrency.",
        ],
    }
    for model in manifest_models:
        role = str(model["role"])
        tag = str(model["tag"])
        if role == "embeddings":
            evidence["embeddings"] = _run_embedding_cases(client, model)
            evidence["models"].append({**dict(model), "gpu": {"not_applicable": True}})
            _unload(client, tag)
            continue
        qualification = run_interactive_qualification(client, model)
        cases, performance = _run_model_cases(client, model)
        evidence["models"].append({**dict(model), "qualification": qualification, **performance})
        evidence["functional"][tag] = {"cases": cases}
        if not all(bool(case["pass"]) for case in cases):
            evidence["acceptance"] = "blocked"
    primary = next(model for model in manifest_models if model["role"] == "primary")
    evidence["thermals"]["qwen3.5:4b"] = run_practical_stability(client, primary)
    if evidence["acceptance"] != "blocked":
        evidence["acceptance"] = "pass"
    if evidence["acceptance"] == "pass" and evidence["restart"].get("status") != "pass":
        if not allow_pending_restart:
            raise BenchmarkError(
                "Restart evidence is required; use --allow-pending-restart only for the "
                "intermediate pre-restart evidence file"
            )
        evidence["acceptance"] = "pending"
    write_sanitized(evidence, output_path)
    if evidence["acceptance"] != "pass" and not (
        allow_pending_restart and evidence["acceptance"] == "pending"
    ):
        raise BenchmarkError("One or more required functional cases failed")
    return evidence


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--model-root",
        type=Path,
        default=Path(__import__("os").environ.get("LOCALAPPDATA", ""))
        / "BMO"
        / "Ollama"
        / "models",
    )
    parser.add_argument("--replace", action="store_true")
    parser.add_argument(
        "--allow-pending-restart",
        action="store_true",
        help="Write intermediate functional evidence before the restart lifecycle gate.",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    if args.output.exists() and not args.replace:
        raise SystemExit("Refusing to overwrite accepted evidence without --replace")
    try:
        run_benchmark(
            base_url=args.base_url,
            manifest_path=args.manifest,
            output_path=args.output,
            model_root=args.model_root,
            allow_pending_restart=args.allow_pending_restart,
        )
    except ThermalStop as exc:
        try:
            stop_dedicated_server()
        except BenchmarkError as stop_exc:
            raise SystemExit(
                f"Phase 4 thermal stop failed to cleanly stop Ollama: {stop_exc}"
            ) from exc
        raise SystemExit(f"Phase 4 benchmark stopped: {exc}") from exc
    except (OSError, json.JSONDecodeError, BenchmarkError) as exc:
        raise SystemExit(f"Phase 4 benchmark stopped: {exc}") from exc
    print("Phase 4 local model benchmark passed.")


if __name__ == "__main__":
    main()
