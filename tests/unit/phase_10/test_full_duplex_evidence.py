from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.phase_10.validate_evidence import validate_evidence

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_PATH = ROOT / "docs/phase_reports/evidence/PHASE_10_FULL_DUPLEX_CONVERSATION.json"


def evidence() -> dict[str, object]:
    return json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))


def test_full_duplex_evidence_is_complete_and_sanitized() -> None:
    payload = evidence()
    validate_evidence(payload)
    assert payload["status"] == "software_pass_physical_pending"
    assert payload["final_exact_head_ci"] == {
        "status": "EXTERNAL_GITHUB_CHECK_REQUIRED",
        "commit": None,
        "run_id": None,
    }


def test_full_duplex_evidence_requires_every_concrete_scenario() -> None:
    payload = evidence()
    scenarios = payload["scenarios"]
    assert isinstance(scenarios, dict)
    del scenarios["barge_in"]
    with pytest.raises(ValueError, match="missing full-duplex scenarios"):
        validate_evidence(payload)


def test_full_duplex_evidence_rejects_self_attested_final_ci() -> None:
    payload = evidence()
    ci = payload["final_exact_head_ci"]
    assert isinstance(ci, dict)
    ci["run_id"] = 123
    with pytest.raises(ValueError, match="must not self-attest final CI"):
        validate_evidence(payload)


def test_full_duplex_evidence_requires_scenario_backed_exactly_once_core_proof() -> None:
    payload = evidence()
    metrics = payload["metrics"]
    assert isinstance(metrics, dict)
    metrics["exactly_once_core_submissions"] = False
    with pytest.raises(ValueError, match="exactly-once Core proof"):
        validate_evidence(payload)


def test_full_duplex_evidence_rejects_audio_retention() -> None:
    payload = evidence()
    privacy = payload["privacy"]
    assert isinstance(privacy, dict)
    privacy["raw_audio_logged"] = True
    with pytest.raises(ValueError, match="privacy field"):
        validate_evidence(payload)
