from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from scripts.phase_06.validate_evidence import validate


def valid_evidence() -> dict[str, Any]:
    return {
        "schema_version": "phase-06-identity-enrollment/v1",
        "tested_git_commit": "a" * 40,
        "migration": {
            "revision": "20260819_0002",
            "upgrade": "pass",
            "downgrade_upgrade_cycle": "pass",
            "alembic_check": "pass",
        },
        "owner": {
            "bootstrap_boundary": "local_cli_only",
            "initial_owner_count": 0,
            "final_owner_count": 1,
            "second_bootstrap": "refused",
        },
        "enrollment": {
            "entropy_bits": 192,
            "default_ttl_minutes": 10,
            "maximum_ttl_minutes": 30,
            "storage": "sha256_only",
            "plaintext_persisted": False,
            "transaction": "postgresql_row_lock",
            "replay": {"attempts": 2, "successes": 1},
            "concurrency": {
                "attempts": 2,
                "successes": 1,
                "device_rows": 1,
                "live_credential_rows": 1,
                "database": "PostgreSQL",
            },
        },
        "credential": {
            "secret_entropy_bits": 256,
            "format": "public_id.secret",
            "storage": "indexed_public_id_plus_sha256_secret",
            "plaintext_persisted": False,
            "constant_time_verification": "hmac.compare_digest",
            "raw_return_count": 1,
        },
        "scope": {
            "approved_vocabulary": [
                "device.self.read",
                "device.heartbeat.write",
                "device.capabilities.report",
                "device.credential.rotate",
            ],
            "wildcard_supported": False,
            "device_requested_authority_rejected": True,
            "missing_scope_status": 403,
        },
        "capability": {
            "storage": "normalized_approved_and_current_reported",
            "reported_subset_enforced": True,
            "unapproved_report_status": 403,
            "device_requested_authority_rejected": True,
        },
        "authentication": {
            "status_matrix": {
                "malformed": 401,
                "unknown": 401,
                "wrong_secret": 401,
                "revoked_credential": 401,
                "revoked_device": 401,
                "disabled_owner": 401,
                "missing_scope": 403,
                "valid_scoped_request": 200,
            },
            "generic_401": True,
        },
        "heartbeat": {"bounded_payload": True, "current_subset_updated": True},
        "rotation": {
            "old_credential_status": 401,
            "new_credential_status": 200,
            "other_credential_status": 200,
        },
        "revocation": {
            "revoked_device_status": "revoked",
            "revoked_credential_status": 401,
            "other_device_status": 200,
        },
        "secret_safety": {
            "database_plaintext": False,
            "api_error_plaintext": False,
            "log_plaintext": False,
            "cli_listing_plaintext": False,
        },
        "tests": {
            "postgresql_concurrency_test": "pass",
            "full_github_validation": "pass",
        },
        "ci": {
            "implementation_status": "success",
            "implementation_exact_commit": "a" * 40,
            "final_evidence_head_status": "success",
            "final_evidence_validated_commit": "b" * 40,
            "final_evidence_run_number": 101,
        },
        "phase_5b": {
            "historical_evidence_changed": False,
            "regression": "accepted_merged_baseline_preserved",
        },
        "phase_1": {"latest_sample_healthy": True},
        "venom_deployment": {
            "performed": False,
            "resource_admission": "NOT_REQUIRED_REPOSITORY_ONLY",
        },
        "phase_7": "NOT_STARTED",
    }


def set_path(data: dict[str, Any], path: str, value: Any) -> None:
    current = data
    parts = path.split(".")
    for part in parts[:-1]:
        current = current[part]
    current[parts[-1]] = value


def test_complete_concrete_evidence_passes() -> None:
    validate(valid_evidence())


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("tested_git_commit", "short"),
        ("migration.downgrade_upgrade_cycle", "missing"),
        ("owner.final_owner_count", 2),
        ("enrollment.entropy_bits", 127),
        ("enrollment.replay.successes", 2),
        ("enrollment.concurrency.successes", 2),
        ("enrollment.concurrency.device_rows", 2),
        ("credential.secret_entropy_bits", 128),
        ("credential.plaintext_persisted", True),
        ("scope.wildcard_supported", True),
        ("scope.missing_scope_status", 200),
        ("capability.reported_subset_enforced", False),
        ("rotation.old_credential_status", 200),
        ("revocation.revoked_credential_status", 200),
        ("ci.final_evidence_head_status", "pending"),
        ("ci.final_evidence_validated_commit", "short"),
        ("phase_5b.historical_evidence_changed", True),
        ("phase_7", "STARTED"),
    ],
)
def test_validator_rejects_incomplete_or_unsafe_claims(path: str, value: Any) -> None:
    evidence = deepcopy(valid_evidence())
    set_path(evidence, path, value)

    with pytest.raises(ValueError):
        validate(evidence)


@pytest.mark.parametrize("key", ["enrollment_code", "raw_credential", "secret_hash"])
def test_validator_rejects_sensitive_fields_anywhere(key: str) -> None:
    evidence = valid_evidence()
    evidence["secret_safety"][key] = "forbidden"

    with pytest.raises(ValueError, match="sensitive evidence key"):
        validate(evidence)


def test_deployed_claim_requires_concrete_resource_maps() -> None:
    evidence = valid_evidence()
    evidence["venom_deployment"] = {
        "performed": True,
        "resource_admission": "pass",
        "resources": {"before": {}, "after": {}, "delta": {}},
    }

    with pytest.raises(ValueError, match="non-empty before resources"):
        validate(evidence)
