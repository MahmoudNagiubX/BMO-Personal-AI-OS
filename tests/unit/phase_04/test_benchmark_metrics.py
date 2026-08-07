from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.phase_04.benchmark_models import (
    BenchmarkError,
    GpuSample,
    InteractiveThermalGovernor,
    _build_parser,
    assert_local_base_url,
    cooldown_state,
    cosine_similarity,
    duration_ns_to_seconds,
    median,
    parse_stream_line,
    thermal_abort_decision,
    thermal_slowdown_from_field,
    thermal_stop_decision,
    thermal_warning_decision,
    tokens_per_second,
    validate_context_case,
    validate_embedding,
    validate_embedding_acceptance,
    validate_interactive_budget,
    validate_interactive_context,
    validate_marker_response,
    validate_pre_request_state,
    validate_structured_output,
    validate_tool_call,
    validate_vision_output,
    write_accepted_evidence,
)


def test_duration_rate_and_median_helpers() -> None:
    assert duration_ns_to_seconds(2_000_000_000) == 2.0
    assert tokens_per_second(10, 2_000_000_000) == 5.0
    assert median([1.0, 3.0, 2.0, 4.0]) == 2.5
    with pytest.raises(BenchmarkError):
        median([])


def test_stream_and_context_validation() -> None:
    assert parse_stream_line('{"done": true}') == {"done": True}
    assert validate_context_case("needle\n", "needle")
    assert validate_marker_response("prefix BMO_OK", "BMO_OK")
    assert not validate_marker_response("", "BMO_OK")
    with pytest.raises(BenchmarkError):
        parse_stream_line("not-json")


def test_structured_and_tool_validation_never_executes() -> None:
    assert validate_structured_output(json.dumps({"status": "ok", "summary": "ready"}))
    assert validate_tool_call(
        {
            "tool_calls": [
                {
                    "function": {
                        "name": "get_synthetic_temperature",
                        "arguments": {"city": "Cairo"},
                    }
                }
            ]
        }
    )
    assert not validate_tool_call({"tool_calls": []})
    assert validate_vision_output({"color": "#FF0000", "shape": "square", "text": "BMO-42"})
    assert not validate_vision_output({"color": "blue", "shape": "square", "text": "BMO-42"})


def test_embedding_cosine_thermal_and_local_url_gates() -> None:
    assert validate_embedding([0.0] * 1024)
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert thermal_stop_decision(87.0)
    assert not thermal_stop_decision(86.9)
    assert thermal_warning_decision(85.0)
    assert thermal_abort_decision(87.0)
    assert not thermal_abort_decision(86.9)
    assert assert_local_base_url("http://127.0.0.1:11434") == "http://127.0.0.1:11434"
    for url in ("http://0.0.0.0:11434", "http://192.0.2.1:11434", "https://127.0.0.1:11434"):
        with pytest.raises(BenchmarkError):
            assert_local_base_url(url)


def test_embedding_acceptance_requires_repeat_consistency_and_near_safe_vector() -> None:
    reference = [1.0] + [0.0] * 1023
    near_safe = [0.5] * 1024
    assert validate_embedding_acceptance(reference, reference, near_safe) == 1.0
    with pytest.raises(BenchmarkError):
        validate_embedding_acceptance(reference, [0.8, 0.6] + [0.0] * 1022, near_safe)
    with pytest.raises(BenchmarkError):
        validate_embedding_acceptance(reference, reference, [0.0] * 1023)


def test_interactive_budget_timeout_and_single_request_gates() -> None:
    validate_interactive_budget("primary", 256, 60.0)
    with pytest.raises(BenchmarkError):
        validate_interactive_budget("primary", 257, 60.0)
    with pytest.raises(BenchmarkError):
        validate_interactive_budget("primary", 64, 60.1)
    validate_interactive_context(4096, 256)
    validate_interactive_context(8192, 32)
    validate_interactive_context(16384, 32)
    with pytest.raises(BenchmarkError):
        validate_interactive_context(32768, 32)
    with pytest.raises(BenchmarkError):
        validate_interactive_context(8192, 33)
    sample = GpuSample(50, 5, 1000, 6141, 20, 100, "P2", False)
    validate_pre_request_state(sample, True, 70.0, [], "qwen3.5:4b")
    with pytest.raises(BenchmarkError):
        validate_pre_request_state(
            GpuSample(71, 5, 1000, 6141, 20, 100, "P2", False),
            True,
            70.0,
            [],
            "qwen3.5:4b",
        )
    governor = InteractiveThermalGovernor(
        object(),
        "qwen3.5:4b",
        "primary",
        sample_once=lambda: sample,
        ac_check=lambda: True,
        memory_check=lambda: 70.0,
    )
    governor._active = True
    with pytest.raises(BenchmarkError):
        governor._run_request(1, 4096, 45.0, lambda _sampler: None)


def test_interactive_temperature_states_and_evidence_abort(tmp_path: Path) -> None:
    assert cooldown_state(84.9) == "wait_20s"
    assert cooldown_state(85.0) == "cool_to_60c"
    assert thermal_warning_decision(85.0)
    assert thermal_abort_decision(87.0)
    assert thermal_stop_decision(87.0)
    output = tmp_path / "evidence.json"
    with pytest.raises(BenchmarkError):
        write_accepted_evidence({"acceptance": "blocked"}, output)
    assert not output.exists()


def test_nvidia_not_active_thermal_field_is_not_a_slowdown() -> None:
    assert not thermal_slowdown_from_field("Not Active")
    assert not thermal_slowdown_from_field("0x0000000000000000")
    assert thermal_slowdown_from_field("Active")


def test_interactive_safety_boundaries_and_group_unload() -> None:
    source = Path("scripts/phase_04/benchmark_models.py").read_text(encoding="utf-8")
    assert "keep_alive=0" in source
    with pytest.raises(SystemExit):
        _build_parser().parse_args(
            [
                "--base-url",
                "http://127.0.0.1:11434",
                "--manifest",
                "manifest.json",
                "--output",
                "evidence.json",
                "--thermal-seconds",
                "90",
            ]
        )


def test_pre_request_gate_unloads_target_on_memory_pressure() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.loaded = True
            self.unload_calls = 0

        def ps(self) -> list[dict[str, str]]:
            return [{"name": "qwen3.5:4b"}] if self.loaded else []

        def stream_generate(self, *_args: object, **_kwargs: object) -> object:
            self.unload_calls += 1
            self.loaded = False
            return object()

    client = FakeClient()
    sample = GpuSample(50, 5, 1000, 6141, 20, 100, "P2", False)
    memory_values = iter([90.0, 70.0])
    governor = InteractiveThermalGovernor(
        client,  # type: ignore[arg-type]
        "qwen3.5:4b",
        "primary",
        sample_once=lambda: sample,
        ac_check=lambda: True,
        memory_check=lambda: next(memory_values),
        sleep=lambda _seconds: None,
    )

    governor._wait_pre_request_gate()

    assert client.unload_calls == 1


def test_pre_request_gate_does_not_block_on_display_gpu_activity() -> None:
    class FakeClient:
        def ps(self) -> list[dict[str, str]]:
            return []

    samples = iter([GpuSample(50, 25, 1000, 6141, 20, 100, "P2", False)])
    governor = InteractiveThermalGovernor(
        FakeClient(),  # type: ignore[arg-type]
        "qwen3.5:4b",
        "primary",
        sample_once=lambda: next(samples),
        ac_check=lambda: True,
        memory_check=lambda: 70.0,
        sleep=lambda _seconds: None,
    )

    governor._wait_pre_request_gate()
