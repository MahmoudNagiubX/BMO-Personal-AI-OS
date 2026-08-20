from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.phase_08_5.validate_evidence import validate

EVIDENCE = Path("docs/phase_reports/evidence/PHASE_08_5_LLAMA_CPP.json")


def test_phase_85_evidence_is_concrete_and_sanitized() -> None:
    validate(json.loads(EVIDENCE.read_text(encoding="utf-8")))


def test_phase_85_evidence_rejects_self_attested_final_head() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    evidence = deepcopy(evidence)
    evidence["ci"]["final_exact_head"]["commit"] = "a" * 40
    with pytest.raises(ValueError):
        validate(evidence)


def test_phase_85_evidence_rejects_non_loopback_endpoint() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    evidence = deepcopy(evidence)
    evidence["runtime"]["endpoint"] = "0.0.0.0:11435"
    with pytest.raises(ValueError):
        validate(evidence)


def test_phase_85_evidence_requires_gateway_failure_isolation() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    evidence = deepcopy(evidence)
    del evidence["acceptance"]["gateway_failure_isolation"]["advanced_restored"]
    with pytest.raises(ValueError):
        validate(evidence)


def test_phase_85_evidence_requires_cross_host_production_proof() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    evidence = deepcopy(evidence)
    del evidence["acceptance"]["cross_host_production"]["exact_model_identity"]
    with pytest.raises(ValueError):
        validate(evidence)
