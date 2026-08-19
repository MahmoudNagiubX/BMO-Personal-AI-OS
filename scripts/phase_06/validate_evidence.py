"""Validate concrete sanitized Phase 6 acceptance evidence."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE = ROOT / "infrastructure/home_server/evidence/phase_06_identity_enrollment.json"
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
FORBIDDEN_KEYS = {
    "authorization",
    "authorization_header",
    "raw_credential",
    "enrollment_code",
    "secret_hash",
    "credential_hash",
    "code_hash",
    "database_url",
}
EXPECTED_SCOPES = {
    "device.self.read",
    "device.heartbeat.write",
    "device.capabilities.report",
    "device.credential.rotate",
}
FINAL_EXACT_HEAD_CI_KEYS = {"required", "verification"}
LEGACY_FINAL_CI_KEYS = {
    "final_evidence_head_status",
    "final_evidence_validated_commit",
    "final_evidence_run_number",
}


def nested(data: Mapping[str, Any], path: str) -> Any:
    """Return a required nested field or raise a deterministic validation error."""

    current: Any = data
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise ValueError(f"missing required evidence field: {path}")
        current = current[part]
    return current


def require_equal(data: Mapping[str, Any], path: str, expected: Any) -> None:
    actual = nested(data, path)
    if actual != expected:
        raise ValueError(f"{path} must equal {expected!r}")


def reject_sensitive_keys(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).casefold()
            if normalized in FORBIDDEN_KEYS:
                raise ValueError(f"sensitive evidence key is forbidden: {path}.{key}")
            reject_sensitive_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_sensitive_keys(child, f"{path}[{index}]")


def validate(data: Mapping[str, Any]) -> None:
    """Reject high-level claims that lack concrete subordinate Phase 6 proof."""

    reject_sensitive_keys(data)
    require_equal(data, "schema_version", "phase-06-identity-enrollment/v1")
    commit = nested(data, "tested_git_commit")
    if not isinstance(commit, str) or COMMIT_PATTERN.fullmatch(commit) is None:
        raise ValueError("tested_git_commit must be a full lowercase commit SHA")
    require_equal(data, "migration.revision", "20260819_0002")
    require_equal(data, "migration.upgrade", "pass")
    require_equal(data, "migration.downgrade_upgrade_cycle", "pass")
    require_equal(data, "migration.alembic_check", "pass")
    require_equal(data, "owner.bootstrap_boundary", "local_cli_only")
    require_equal(data, "owner.initial_owner_count", 0)
    require_equal(data, "owner.final_owner_count", 1)
    require_equal(data, "owner.second_bootstrap", "refused")

    entropy = nested(data, "enrollment.entropy_bits")
    if not isinstance(entropy, int) or isinstance(entropy, bool) or entropy < 128:
        raise ValueError("enrollment.entropy_bits must be at least 128")
    require_equal(data, "enrollment.default_ttl_minutes", 10)
    require_equal(data, "enrollment.maximum_ttl_minutes", 30)
    require_equal(data, "enrollment.storage", "sha256_only")
    require_equal(data, "enrollment.plaintext_persisted", False)
    require_equal(data, "enrollment.transaction", "postgresql_row_lock")
    require_equal(data, "enrollment.replay.attempts", 2)
    require_equal(data, "enrollment.replay.successes", 1)
    require_equal(data, "enrollment.concurrency.attempts", 2)
    require_equal(data, "enrollment.concurrency.successes", 1)
    require_equal(data, "enrollment.concurrency.device_rows", 1)
    require_equal(data, "enrollment.concurrency.live_credential_rows", 1)
    require_equal(data, "enrollment.concurrency.database", "PostgreSQL")

    secret_bits = nested(data, "credential.secret_entropy_bits")
    if not isinstance(secret_bits, int) or isinstance(secret_bits, bool) or secret_bits < 256:
        raise ValueError("credential.secret_entropy_bits must be at least 256")
    require_equal(data, "credential.format", "public_id.secret")
    require_equal(data, "credential.storage", "indexed_public_id_plus_sha256_secret")
    require_equal(data, "credential.plaintext_persisted", False)
    require_equal(data, "credential.constant_time_verification", "hmac.compare_digest")
    require_equal(data, "credential.raw_return_count", 1)

    scopes = nested(data, "scope.approved_vocabulary")
    if not isinstance(scopes, list) or set(scopes) != EXPECTED_SCOPES:
        raise ValueError("scope.approved_vocabulary must contain exactly Phase 6 scopes")
    require_equal(data, "scope.wildcard_supported", False)
    require_equal(data, "scope.device_requested_authority_rejected", True)
    require_equal(data, "scope.missing_scope_status", 403)
    require_equal(data, "capability.storage", "normalized_approved_and_current_reported")
    require_equal(data, "capability.reported_subset_enforced", True)
    require_equal(data, "capability.unapproved_report_status", 403)
    require_equal(data, "capability.device_requested_authority_rejected", True)

    expected_auth = {
        "malformed": 401,
        "unknown": 401,
        "wrong_secret": 401,
        "revoked_credential": 401,
        "revoked_device": 401,
        "disabled_owner": 401,
        "missing_scope": 403,
        "valid_scoped_request": 200,
    }
    require_equal(data, "authentication.status_matrix", expected_auth)
    require_equal(data, "authentication.generic_401", True)
    require_equal(data, "heartbeat.bounded_payload", True)
    require_equal(data, "heartbeat.current_subset_updated", True)
    require_equal(data, "rotation.old_credential_status", 401)
    require_equal(data, "rotation.new_credential_status", 200)
    require_equal(data, "rotation.other_credential_status", 200)
    require_equal(data, "revocation.revoked_device_status", "revoked")
    require_equal(data, "revocation.revoked_credential_status", 401)
    require_equal(data, "revocation.other_device_status", 200)
    require_equal(data, "secret_safety.database_plaintext", False)
    require_equal(data, "secret_safety.api_error_plaintext", False)
    require_equal(data, "secret_safety.log_plaintext", False)
    require_equal(data, "secret_safety.cli_listing_plaintext", False)
    require_equal(data, "tests.postgresql_concurrency_test", "pass")
    require_equal(data, "tests.full_github_validation", "pass")
    require_equal(data, "ci.implementation_status", "success")
    require_equal(data, "ci.implementation_exact_commit", commit)
    ci = nested(data, "ci")
    if not isinstance(ci, Mapping):
        raise ValueError("ci must be an object")
    legacy_keys = LEGACY_FINAL_CI_KEYS.intersection(ci)
    if legacy_keys:
        raise ValueError(
            "ci must not self-attest final exact-head commit/status/run: "
            + ", ".join(sorted(legacy_keys))
        )
    final_exact_head_ci = nested(data, "ci.final_exact_head_ci")
    if not isinstance(final_exact_head_ci, Mapping):
        raise ValueError("ci.final_exact_head_ci must be an object")
    if set(final_exact_head_ci) != FINAL_EXACT_HEAD_CI_KEYS:
        raise ValueError("ci.final_exact_head_ci must contain only required and verification")
    require_equal(data, "ci.final_exact_head_ci.required", True)
    require_equal(
        data,
        "ci.final_exact_head_ci.verification",
        "EXTERNAL_GITHUB_CHECK_REQUIRED",
    )
    require_equal(data, "phase_5b.historical_evidence_changed", False)
    require_equal(data, "phase_5b.regression", "accepted_merged_baseline_preserved")
    require_equal(data, "phase_1.latest_sample_healthy", True)
    require_equal(data, "phase_7", "NOT_STARTED")

    deployed = nested(data, "venom_deployment.performed")
    if not isinstance(deployed, bool):
        raise ValueError("venom_deployment.performed must be a boolean")
    if deployed:
        require_equal(data, "venom_deployment.resource_admission", "pass")
        for period in ("before", "after", "delta"):
            resource_data = nested(data, f"venom_deployment.resources.{period}")
            if not isinstance(resource_data, Mapping) or not resource_data:
                raise ValueError(f"deployed evidence requires non-empty {period} resources")
    else:
        require_equal(
            data,
            "venom_deployment.resource_admission",
            "NOT_REQUIRED_REPOSITORY_ONLY",
        )


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_EVIDENCE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("evidence root must be an object")
        validate(payload)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Phase 6 evidence validation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print("Phase 6 identity and enrollment evidence validation passed.")


if __name__ == "__main__":
    main()
