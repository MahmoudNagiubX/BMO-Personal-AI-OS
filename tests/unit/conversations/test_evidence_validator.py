from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from scripts.phase_07.validate_evidence import validate

EVIDENCE_PATH = Path("infrastructure/home_server/evidence/phase_07_text_conversation.json")


def valid_evidence() -> dict[str, Any]:
    return json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))


def test_complete_concrete_evidence_passes() -> None:
    validate(valid_evidence())


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("tested_git_commit", "short"),
        ("domain.tables", ["conversations"]),
        ("authorization.phase_7_scopes", ["conversation.read"]),
        ("idempotency.replay_results", 2),
        ("active_run.race_busy", 0),
        ("gateway.boundary", "direct_ollama"),
        ("gateway.tool_execution", True),
        ("execution.cancel.race", "succeeded"),
        ("trace.persisted_prompt_or_response_content", True),
        ("phase_8", "STARTED"),
    ],
)
def test_validator_rejects_summary_only_or_unsafe_claims(path: str, value: Any) -> None:
    evidence = deepcopy(valid_evidence())
    current = evidence
    parts = path.split(".")
    for part in parts[:-1]:
        current = current[part]
    current[parts[-1]] = value

    with pytest.raises(ValueError):
        validate(evidence)


def test_validator_rejects_arbitrary_final_implementation_claim() -> None:
    evidence = valid_evidence()
    evidence["ci"]["implementation_exact_commit"] = "b" * 40
    with pytest.raises(ValueError):
        validate(evidence)


def test_validator_requires_external_final_exact_head_ci() -> None:
    evidence = valid_evidence()
    evidence["ci"]["final_exact_head_ci"] = {
        "required": True,
        "verification": "success",
        "commit": "b" * 40,
    }
    with pytest.raises(ValueError):
        validate(evidence)


@pytest.mark.parametrize(
    "path",
    [
        "reconciliation.stale_before_operation",
        "websocket.revalidation.credential_revoked_code",
        "websocket.disconnect_observer.explicit_receive_task",
        "event_sequence.close_finalization_postgresql_race",
        "executor.exception_boundary",
    ],
)
def test_validator_requires_concrete_lifecycle_recovery_fields(path: str) -> None:
    evidence = valid_evidence()
    current = evidence
    parts = path.split(".")
    for part in parts[:-1]:
        current = current[part]
    del current[parts[-1]]
    with pytest.raises(ValueError, match="missing required evidence field"):
        validate(evidence)


def test_validator_rejects_legacy_self_attestation() -> None:
    evidence = valid_evidence()
    evidence["ci"]["final_evidence_validated_commit"] = "b" * 40
    with pytest.raises(ValueError, match="must not self-attest"):
        validate(evidence)


@pytest.mark.parametrize("key", ["authorization_header", "raw_prompt", "provider_payload"])
def test_validator_rejects_sensitive_evidence_keys(key: str) -> None:
    evidence = valid_evidence()
    evidence["security"][key] = "forbidden"
    with pytest.raises(ValueError, match="sensitive evidence key"):
        validate(evidence)
