"""Validate stable, safe idle readiness before starting the Phase 4 runtime."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.phase_04.benchmark_models import BenchmarkError, GpuSample, GpuSampler, median

IDLE_SAMPLE_SECONDS = 120
IDLE_MAX_TEMPERATURE_C = 65.0
IDLE_MAX_UTILIZATION_PERCENT = 15.0
IDLE_MEDIAN_UTILIZATION_PERCENT = 5.0
IDLE_MAX_TREND_C_PER_MINUTE = 0.5


@dataclass(frozen=True, slots=True)
class IdleSystemState:
    """Sanitized system state required while collecting idle samples."""

    ollama_processes: int
    runner_processes: int
    listener_count: int
    loaded_models: int
    ac_connected: bool


def _median(values: Sequence[float]) -> float:
    if not values:
        raise BenchmarkError("Stable idle readiness has no samples")
    return median(values)


def validate_stable_idle_readiness(
    samples: Sequence[GpuSample],
    states: Sequence[IdleSystemState],
) -> dict[str, Any]:
    """Return sanitized readiness metrics or reject an unsafe idle window."""

    if len(samples) < IDLE_SAMPLE_SECONDS or len(states) != len(samples):
        raise BenchmarkError("Stable idle readiness has insufficient samples")
    numeric_values = [sample.temperature_c for sample in samples] + [
        sample.utilization_percent for sample in samples
    ]
    if not all(math.isfinite(value) and value >= 0 for value in numeric_values):
        raise BenchmarkError("Stable idle readiness contains invalid samples")

    temperatures = [sample.temperature_c for sample in samples]
    utilization = [sample.utilization_percent for sample in samples]
    first_median = _median(temperatures[:30])
    last_median = _median(temperatures[-30:])
    trend = (last_median - first_median) / ((len(samples) - 1) / 60.0)
    max_temperature = max(temperatures)
    median_temperature = _median(temperatures)
    max_utilization = max(utilization)
    median_utilization = _median(utilization)
    state_failures = any(
        state.ollama_processes != 0
        or state.runner_processes != 0
        or state.listener_count != 0
        or state.loaded_models != 0
        or not state.ac_connected
        for state in states
    )
    thermal_slowdown = any(sample.thermal_slowdown for sample in samples)
    if (
        max_temperature > IDLE_MAX_TEMPERATURE_C
        or median_temperature > 62.0
        or abs(last_median - first_median) > 2.0
        or last_median > first_median + 1.0
        or trend > IDLE_MAX_TREND_C_PER_MINUTE
        or max_utilization > IDLE_MAX_UTILIZATION_PERCENT
        or median_utilization > IDLE_MEDIAN_UTILIZATION_PERCENT
        or state_failures
        or thermal_slowdown
    ):
        raise BenchmarkError("Stable idle readiness gate failed")

    return {
        "acceptance": "pass",
        "sample_count": len(samples),
        "duration_seconds": len(samples),
        "min_temperature_c": round(min(temperatures), 3),
        "max_temperature_c": round(max_temperature, 3),
        "median_temperature_c": round(median_temperature, 3),
        "first_30s_median_temperature_c": round(first_median, 3),
        "last_30s_median_temperature_c": round(last_median, 3),
        "temperature_delta_c": round(last_median - first_median, 3),
        "temperature_trend_c_per_minute": round(trend, 6),
        "max_utilization_percent": round(max_utilization, 3),
        "median_utilization_percent": round(median_utilization, 3),
        "max_vram_used_mib": round(max(sample.vram_used_mib for sample in samples), 3),
        "thermal_slowdown": thermal_slowdown,
        "performance_states": sorted({sample.pstate for sample in samples}),
        "ollama_processes": max(state.ollama_processes for state in states),
        "runner_processes": max(state.runner_processes for state in states),
        "listener_count": max(state.listener_count for state in states),
        "loaded_models": max(state.loaded_models for state in states),
        "ac_connected": all(state.ac_connected for state in states),
    }


def _system_state() -> IdleSystemState:
    """Collect only sanitized process, listener, model, and AC state."""

    command = (
        "$processes=@(Get-Process -ErrorAction SilentlyContinue | Where-Object "
        "{$_.ProcessName -match '^(ollama|llama-server)'}); "
        "$listeners=@(Get-NetTCPConnection -LocalPort 11434 -State Listen "
        "-ErrorAction SilentlyContinue); "
        "$battery=@(Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue | "
        "Select-Object -ExpandProperty BatteryStatus); "
        "$ac=($battery.Count -gt 0 -and @($battery | Where-Object "
        "{$_ -in @(2,6,7,8,9,11)}).Count -eq $battery.Count); "
        "[pscustomobject]@{processes=$processes.Count; "
        "listeners=$listeners.Count;ac=$ac} | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BenchmarkError("Idle system-state sampling failed") from exc
    if completed.returncode != 0:
        raise BenchmarkError("Idle system-state sampling failed")
    try:
        payload = json.loads(completed.stdout)
        process_count = int(payload["processes"])
        listener_count = int(payload["listeners"])
        ac_connected = bool(payload["ac"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise BenchmarkError("Idle system-state sample was invalid") from exc
    health_available = False
    loaded_models = 0
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=2) as response:
            body = json.load(response)
        models = body.get("models", []) if isinstance(body, dict) else []
        loaded_models = len(models) if isinstance(models, list) else 0
        health_available = True
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        pass
    if health_available:
        listener_count = max(listener_count, 1)
    return IdleSystemState(
        ollama_processes=process_count,
        runner_processes=process_count,
        listener_count=listener_count,
        loaded_models=loaded_models,
        ac_connected=ac_connected,
    )


def collect_stable_idle_readiness(
    *,
    duration_seconds: int = IDLE_SAMPLE_SECONDS,
    sample_once: Callable[[], GpuSample] = GpuSampler._sample_once,
    state_once: Callable[[], IdleSystemState] = _system_state,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Collect one-second samples and enforce stable idle readiness."""

    if duration_seconds < IDLE_SAMPLE_SECONDS:
        raise BenchmarkError("Stable idle readiness duration is too short")
    samples: list[GpuSample] = []
    states: list[IdleSystemState] = []
    started = monotonic()
    for index in range(duration_seconds):
        samples.append(sample_once())
        states.append(state_once())
        target = started + index + 1
        remaining = target - monotonic()
        if remaining > 0:
            sleep(remaining)
    return validate_stable_idle_readiness(samples, states)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-seconds", type=int, default=IDLE_SAMPLE_SECONDS)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    try:
        readiness = collect_stable_idle_readiness(duration_seconds=args.duration_seconds)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(readiness, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except (BenchmarkError, OSError) as exc:
        raise SystemExit(f"Phase 4 stable idle readiness stopped: {exc}") from exc
    print("Phase 4 stable idle readiness passed.")


if __name__ == "__main__":
    main()
