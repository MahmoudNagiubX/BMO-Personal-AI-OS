from __future__ import annotations

from scripts.phase_10.run_wake_score_calibration import _finalize, _sweep


def _sample(kind: str, score: float) -> dict[str, object]:
    return {"kind": kind, "max_probability": score}


def test_threshold_sweep_reports_recall_misses_and_false_activations() -> None:
    rows = _sweep(
        [
            _sample("positive", 0.82),
            _sample("positive", 0.91),
            _sample("negative", 0.12),
            _sample("negative", 0.21),
        ]
    )

    row = next(item for item in rows if item["threshold"] == 0.5)
    assert row["positive_recall"] == 1.0
    assert row["misses"] == 0
    assert row["false_activations"] == 0


def test_finalize_selects_fixed_threshold_only_with_clear_margin() -> None:
    report: dict[str, object] = {
        "samples": [
            _sample("positive", 0.82),
            _sample("positive", 0.91),
            _sample("negative", 0.12),
            _sample("negative", 0.21),
        ]
    }

    _finalize(report)

    decision = report["decision"]
    assert isinstance(decision, dict)
    assert decision["meaningful_separation"] is True
    assert decision["candidate_threshold"] == 0.5
    assert decision["next_action"] == "rerun fresh Stage A with fixed threshold"


def test_finalize_rejects_overlapping_distributions_for_vosk_evaluation() -> None:
    report: dict[str, object] = {
        "samples": [
            _sample("positive", 0.42),
            _sample("positive", 0.51),
            _sample("negative", 0.45),
            _sample("negative", 0.55),
        ]
    }

    _finalize(report)

    decision = report["decision"]
    assert isinstance(decision, dict)
    assert decision["meaningful_separation"] is False
    assert decision["candidate_threshold"] is None
    assert "Vosk" in decision["next_action"]
