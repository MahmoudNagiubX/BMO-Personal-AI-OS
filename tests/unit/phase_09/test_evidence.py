from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.phase_09.validate_evidence import EVIDENCE, validate


def _evidence() -> dict[str, object]:
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def test_committed_phase09_evidence_is_strict_and_sanitized() -> None:
    validate()


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("physical_prerequisite", "phase6_deployment_present"), False),
        (("physical_prerequisite", "postgresql_active"), False),
        (("physical_tool_gate", "telemetry"), "FAILED"),
        (("physical_tool_gate", "workflow_approval_execution"), "BLOCKED"),
        (("protocol", "inbound_tuf_listener_defined"), True),
        (("identity", "reusable_plaintext_persistence"), True),
        (("phase10",), "STARTED"),
    ],
)
def test_validator_rejects_false_acceptance_claims(path: tuple[str, ...], value: object) -> None:
    data = deepcopy(_evidence())
    target = data
    for part in path[:-1]:
        target = target[part]  # type: ignore[assignment,index]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        validate(data)


def test_validator_rejects_sensitive_paths_and_final_ci_self_attestation() -> None:
    sensitive = deepcopy(_evidence())
    sensitive["local_path"] = str(Path("C:/Users/example/private"))
    with pytest.raises(ValueError, match="unsanitized"):
        validate(sensitive)

    self_attested = deepcopy(_evidence())
    self_attested["ci"]["final_exact_head"]["status"] = "PASS"  # type: ignore[index]
    with pytest.raises(ValueError, match="external governance"):
        validate(self_attested)
