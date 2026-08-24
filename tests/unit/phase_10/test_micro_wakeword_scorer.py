from __future__ import annotations

from scripts.phase_10.debug_micro_wakeword_scorer import _evaluate, _preprocessing_contract


def _sample(name: str, source: str, input_mean: float, output_mean: float) -> dict[str, object]:
    return {
        "name": name,
        "source": source,
        "diagnostics": {
            "input_tensor_stats": {
                "min": input_mean - 1.0,
                "max": input_mean + 1.0,
                "mean": input_mean,
                "std": 1.0,
            },
            "model_output_stats": {
                "min": output_mean - 0.01,
                "max": output_mean + 0.01,
                "mean": output_mean,
                "std": 0.01,
            },
        },
    }


def test_scorer_evaluation_requires_meaningful_positive_separation() -> None:
    result = _evaluate(
        [
            _sample("silence", "controlled", -128.0, 0.44),
            _sample("random_noise", "controlled", -80.0, 0.45),
            _sample("synthetic_jarvis", "synthetic_local_tts", -116.0, 0.4501),
        ]
    )

    assert result["controlled_input_tensor_distinct_across_samples"] is True
    assert result["synthetic_positive_measurably_separated"] is False
    assert result["synthetic_positive_mean_minus_nearest_control"] == 0.0001


def test_preprocessing_contract_matches_pinned_runtime_step() -> None:
    contract = _preprocessing_contract(
        {"micro": {"feature_step_size": 10, "sliding_window_size": 5}}
    )

    assert contract["sample_rate_hz"] == 16_000
    assert contract["feature_shape"] == [1, 1, 40]
    assert contract["runtime_matches_training_step"] is True
    assert contract["sliding_window_size"] == 5
