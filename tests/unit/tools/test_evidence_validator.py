from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from scripts.phase_08.validate_evidence import validate

EVIDENCE_PATH = Path(
    "infrastructure/home_server/evidence/phase_08_tool_permission_approval_audit.json"
)


def valid_evidence() -> dict[str, Any]:
    return json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))


def test_evidence_validator_accepts_complete_shape() -> None:
    evidence = valid_evidence()
    evidence["tested_git_commit"] = "a" * 40
    evidence["ci"]["implementation_exact_commit"] = "a" * 40
    evidence["ci"]["implementation_run_number"] = 1
    validate(evidence)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("registry.published_tools", ["unsafe"]),
        ("authorization.phase_8_scopes", ["*"]),
        ("binding.raw_arguments_authority", True),
        ("approval.replay", "blind_retry"),
        ("executor.shell", True),
        ("phase_9", "STARTED"),
        (
            "ci.final_exact_head_ci",
            {"required": True, "verification": "success", "commit": "b" * 40},
        ),
    ],
)
def test_evidence_rejects_unsafe_or_summary_claims(path: str, value: Any) -> None:
    evidence = valid_evidence()
    evidence["tested_git_commit"] = "a" * 40
    evidence["ci"]["implementation_exact_commit"] = "a" * 40
    evidence["ci"]["implementation_run_number"] = 1
    current = evidence
    parts = path.split(".")
    for part in parts[:-1]:
        current = current[part]
    current[parts[-1]] = value
    with pytest.raises(ValueError):
        validate(evidence)


def test_evidence_rejects_sensitive_keys_and_self_attestation() -> None:
    evidence = valid_evidence()
    evidence["tested_git_commit"] = "a" * 40
    evidence["ci"]["implementation_exact_commit"] = "a" * 40
    evidence["ci"]["implementation_run_number"] = 1
    evidence["security"]["raw_prompt"] = "forbidden"
    with pytest.raises(ValueError, match="sensitive evidence key"):
        validate(evidence)
    evidence = deepcopy(valid_evidence())
    evidence["tested_git_commit"] = "a" * 40
    evidence["ci"]["implementation_exact_commit"] = "a" * 40
    evidence["ci"]["implementation_run_number"] = 1
    evidence["ci"]["final_evidence_validated_commit"] = "b" * 40
    with pytest.raises(ValueError, match="self-attest"):
        validate(evidence)


def test_evidence_validator_rejects_missing_threat_id(tmp_path: Path) -> None:
    evidence = valid_evidence()
    evidence["tested_git_commit"] = "a" * 40
    evidence["ci"]["implementation_exact_commit"] = "a" * 40
    evidence["ci"]["implementation_run_number"] = 1

    bad_threat_model = tmp_path / "INCOMPLETE_THREAT_MODEL.md"
    bad_threat_model.write_text("# Threat Model\n\n`prompt_injection` only\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing mandatory threat ID"):
        validate(evidence, threat_model_path=bad_threat_model)


def test_evidence_validator_rejects_missing_threat_model_file(tmp_path: Path) -> None:
    evidence = valid_evidence()
    evidence["tested_git_commit"] = "a" * 40
    evidence["ci"]["implementation_exact_commit"] = "a" * 40
    evidence["ci"]["implementation_run_number"] = 1

    with pytest.raises(ValueError, match="threat model file not found"):
        validate(evidence, threat_model_path=tmp_path / "nonexistent.md")
