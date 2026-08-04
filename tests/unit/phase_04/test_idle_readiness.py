from __future__ import annotations

import math

import pytest

from scripts.phase_04.benchmark_models import BenchmarkError, GpuSample
from scripts.phase_04.idle_readiness import IdleSystemState, validate_stable_idle_readiness


def sample_window(
    temperature: float | list[float] = 58.0,
    utilization: float | list[float] = 2.0,
    *,
    slowdown: bool = False,
) -> list[GpuSample]:
    temperatures = [temperature] if isinstance(temperature, float) else temperature
    utilizations = [utilization] if isinstance(utilization, float) else utilization
    values = [temperatures[index % len(temperatures)] for index in range(120)]
    uses = [utilizations[index % len(utilizations)] for index in range(120)]
    return [
        GpuSample(value, uses[index], 1200, 6141, 20, 80, "P8", slowdown)
        for index, value in enumerate(values)
    ]


def idle_states(*, ac: bool = True, listener: int = 0) -> list[IdleSystemState]:
    return [IdleSystemState(0, 0, listener, 0, ac) for _ in range(120)]


def test_stable_idle_readiness_accepts_58c_and_64c() -> None:
    assert validate_stable_idle_readiness(sample_window(), idle_states())["acceptance"] == "pass"
    assert (
        validate_stable_idle_readiness(sample_window([64.0, 60.0]), idle_states())["acceptance"]
        == "pass"
    )


@pytest.mark.parametrize(
    "samples,states",
    [
        (sample_window(66.0), idle_states()),
        (sample_window([58.0] * 60 + [64.0] * 60), idle_states()),
        (sample_window(58.0, 20.0), idle_states()),
        (sample_window(58.0, 6.0), idle_states()),
        (sample_window(58.0, slowdown=True), idle_states()),
        (sample_window(), idle_states(listener=1)),
        (sample_window(), idle_states(ac=False)),
    ],
)
def test_stable_idle_readiness_rejects_unsafe_windows(
    samples: list[GpuSample], states: list[IdleSystemState]
) -> None:
    with pytest.raises(BenchmarkError):
        validate_stable_idle_readiness(samples, states)


def test_stable_idle_readiness_rejects_invalid_or_insufficient_samples() -> None:
    with pytest.raises(BenchmarkError):
        validate_stable_idle_readiness(sample_window()[:119], idle_states()[:119])
    invalid = sample_window()
    invalid[0] = GpuSample(math.nan, 2, 1200, 6141, 20, 80, "P8", False)
    with pytest.raises(BenchmarkError):
        validate_stable_idle_readiness(invalid, idle_states())
