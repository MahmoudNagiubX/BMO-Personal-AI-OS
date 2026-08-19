"""Validate concrete sanitized Phase 8 tool-platform evidence."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE = (
    ROOT / "infrastructure/home_server/evidence/phase_08_tool_permission_approval_audit.json"
)
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
FORBIDDEN_KEYS = {
    "authorization_header",
    "bearer",
    "credential",
    "raw_credential",
    "enrollment_code",
    "secret",
    "secret_hash",
    "private_key",
    "password",
    "database_url",
    "raw_model_output",
    "raw_prompt",
    "provider_payload",
    "chain_of_thought",
}
PHASE_6_SCOPES = {
    "device.self.read",
    "device.heartbeat.write",
    "device.capabilities.report",
    "device.credential.rotate",
}
PHASE_7_SCOPES = {
    "conversation.read",
    "conversation.write",
    "conversation.stream",
    "conversation.run.cancel",
}
PHASE_8_SCOPES = {
    "tool.catalog.read",
    "tool.request",
    "approval.read",
    "approval.decide",
    "audit.read",
}
FINAL_CI_KEYS = {"required", "verification"}
LEGACY_CI_KEYS = {
    "final_evidence_head_status",
    "final_evidence_validated_commit",
    "final_evidence_run_number",
}
PUBLISHED_TOOLS = [
    "phase8.consequential.echo",
    "phase8.critical.echo",
    "phase8.invalid.output",
    "phase8.offline.read",
    "phase8.reversible.set",
    "phase8.slow.cancellable",
    "phase8.status.read",
    "phase8.verification.fail",
]


def nested(data: Mapping[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise ValueError(f"missing required evidence field: {path}")
        current = current[part]
    return current


def require_equal(data: Mapping[str, Any], path: str, expected: Any) -> None:
    if nested(data, path) != expected:
        raise ValueError(f"{path} must equal {expected!r}")


def require_positive_int(data: Mapping[str, Any], path: str) -> int:
    value = nested(data, path)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{path} must be a positive integer")
    return value


def reject_sensitive_keys(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).casefold() in FORBIDDEN_KEYS:
                raise ValueError(f"sensitive evidence key is forbidden: {path}.{key}")
            reject_sensitive_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_sensitive_keys(child, f"{path}[{index}]")


def validate(data: Mapping[str, Any]) -> None:
    """Reject summary-only, caller-controlled, or self-attested evidence."""

    reject_sensitive_keys(data)
    require_equal(data, "schema_version", "phase-08-tool-permission-approval-audit/v1")
    commit = nested(data, "tested_git_commit")
    if not isinstance(commit, str) or COMMIT_PATTERN.fullmatch(commit) is None:
        raise ValueError("tested_git_commit must be a full lowercase commit SHA")
    require_equal(data, "migration.revision", "20260819_0004")
    for field in ("upgrade", "downgrade_upgrade_cycle", "alembic_check"):
        require_equal(data, f"migration.{field}", "pass")
    require_equal(data, "migration.rollback_revision", "20260819_0003")

    require_equal(data, "registry.published_tools", PUBLISHED_TOOLS)
    require_equal(data, "registry.forbidden_tool_present_for_deny_test", True)
    require_equal(data, "registry.forbidden_tool_published", False)
    require_equal(data, "registry.unknown_name_or_version", "deny")
    require_equal(data, "registry.risk_source", "static_descriptor_only")
    require_equal(data, "registry.caller_sets_risk", False)
    require_equal(data, "registry.caller_sets_policy", False)
    require_equal(data, "schemas.extra_fields", "rejected")
    require_equal(data, "schemas.coercion", "rejected")
    require_equal(data, "schemas.non_finite_numbers", "rejected")
    require_equal(data, "schemas.output_validation", True)
    require_equal(data, "binding.canonical_json", "sorted_compact_sha256")
    require_equal(data, "binding.raw_arguments_authority", False)
    require_equal(data, "binding.changed_arguments", "deny")
    require_equal(data, "binding.preview_deterministic", True)

    require_equal(data, "authorization.phase_6_scopes", sorted(PHASE_6_SCOPES))
    require_equal(data, "authorization.phase_7_scopes", sorted(PHASE_7_SCOPES))
    require_equal(data, "authorization.phase_8_scopes", sorted(PHASE_8_SCOPES))
    require_equal(
        data,
        "authorization.active_scopes",
        sorted(PHASE_6_SCOPES | PHASE_7_SCOPES | PHASE_8_SCOPES),
    )
    require_equal(data, "authorization.wildcard_supported", False)
    require_equal(data, "authorization.owner_mutation_remote", False)
    require_equal(data, "authorization.llm_decides_risk_permission_approval", False)

    require_equal(data, "permission.decision_values", ["allow", "require_approval", "deny"])
    require_equal(data, "permission.forbidden_autonomous", "deny")
    require_equal(data, "permission.offline", "deny")
    require_equal(data, "permission.degraded", "deny_or_explicit_safe_policy")
    require_equal(data, "permission.capability_subset", True)
    require_equal(data, "permission.audit_before_consequential", True)

    require_equal(data, "approval.exact_owner", True)
    require_equal(data, "approval.ttl.consequential_minutes", 10)
    require_equal(data, "approval.ttl.critical_minutes", 3)
    require_equal(
        data,
        "approval.binding",
        ["owner", "device", "tool", "version", "risk", "argument_digest", "policy_version"],
    )
    require_equal(data, "approval.replay", "single_atomic_consume")
    require_equal(data, "approval.expiry", "database_time_checked_before_decision_and_consume")
    require_equal(data, "approval.cancellation_race", "cancel_or_approve_one_terminal_winner")

    require_equal(data, "budgets.max_proposals_per_run", 4)
    require_equal(data, "budgets.max_executions_per_run", 3)
    require_equal(data, "budgets.max_approval_prompts_per_run", 2)
    require_equal(data, "budgets.rate_limits_database_backed", True)
    require_equal(data, "budgets.concurrent_increment", "row_lock_or_unique_conflict")
    require_equal(data, "availability.states", ["available", "degraded", "offline"])
    require_equal(data, "availability.unavailable_executes", False)
    require_equal(
        data,
        "api.endpoints",
        [
            "GET /api/v1/tools",
            "GET /api/v1/tools/{name}",
            "POST /api/v1/tool-calls",
            "POST /api/v1/tool-calls/{tool_call_id}/cancel",
            "GET /api/v1/approvals",
            "GET /api/v1/approvals/{approval_id}",
            "POST /api/v1/approvals/{approval_id}/approve",
            "POST /api/v1/approvals/{approval_id}/reject",
            "GET /api/v1/audit",
        ],
    )
    require_equal(data, "api.authentication", "opaque_bearer_scopes")
    require_equal(data, "api.validation_errors_sanitized", True)

    require_equal(data, "executor.input", "typed_validated_bound_request")
    require_equal(data, "executor.shell", False)
    require_equal(data, "executor.synthetic_only", True)
    require_equal(data, "executor.output_schema_failure", "failed_not_success")
    require_equal(data, "executor.verification_failure", "failed_not_success")
    require_equal(data, "executor.raw_model_or_auth_input", False)
    require_equal(
        data,
        "sandbox.policies",
        [
            "core_readonly",
            "satellite_typed",
            "browser_isolated",
            "home_assistant_selected",
            "forbidden",
        ],
    )
    require_equal(data, "sandbox.general_shell", False)

    require_equal(data, "audit.append_only", True)
    require_equal(data, "audit.redacted", True)
    require_equal(data, "audit.raw_arguments", False)
    require_equal(data, "audit.raw_provider_payload", False)
    require_equal(
        data,
        "audit.events",
        [
            "tool.proposed",
            "tool.denied",
            "tool.awaiting_approval",
            "approval.required",
            "approval.approved",
            "approval.rejected",
            "approval.expired",
            "tool.started",
            "tool.succeeded",
            "tool.failed",
            "tool.cancelled",
        ],
    )
    require_equal(data, "audit.failure_blocks_consequential", True)
    require_equal(
        data,
        "websocket.approval_events",
        [
            "tool.proposed",
            "tool.awaiting_approval",
            "approval.required",
            "approval.approved",
            "approval.rejected",
            "approval.expired",
            "tool.started",
            "tool.succeeded",
            "tool.failed",
            "tool.cancelled",
        ],
    )
    require_equal(data, "websocket.approval_event_payload_redacted", True)
    require_equal(data, "agent_runtime.max_proposals", 3)
    require_equal(data, "agent_runtime.model_proposal_is_data", True)
    require_equal(data, "agent_runtime.direct_executor_path", False)
    require_equal(data, "agent_runtime.approval_pauses", True)
    require_equal(data, "agent_runtime.tool_loop_budget", True)
    require_equal(data, "phase_9", "NOT_STARTED")
    require_equal(data, "phase_5b_behavior_preserved", True)
    require_equal(data, "venom_deployment.performed", False)
    require_equal(data, "venom_deployment.resource_admission", "NOT_REQUIRED_REPOSITORY_ONLY")

    require_equal(data, "tests.unit_platform", "pass")
    require_equal(data, "tests.postgresql_races", "pass")
    require_positive_int(data, "tests.unit_count")
    require_positive_int(data, "tests.integration_count")
    require_equal(data, "security.no_public_or_lan_api", True)
    require_equal(data, "security.no_secrets_or_personal_data", True)
    require_equal(data, "rollback.normal_revert", True)
    require_equal(data, "rollback.previous_phase7_untouched", True)

    require_equal(data, "ci.implementation_status", "success")
    require_equal(data, "ci.implementation_exact_commit", commit)
    require_positive_int(data, "ci.implementation_run_number")
    ci = nested(data, "ci")
    if not isinstance(ci, Mapping) or LEGACY_CI_KEYS.intersection(ci):
        raise ValueError("ci must not self-attest final exact-head commit/status/run")
    final = nested(data, "ci.final_exact_head_ci")
    if not isinstance(final, Mapping) or set(final) != FINAL_CI_KEYS:
        raise ValueError("ci.final_exact_head_ci must contain only required and verification")
    require_equal(data, "ci.final_exact_head_ci.required", True)
    require_equal(data, "ci.final_exact_head_ci.verification", "EXTERNAL_GITHUB_CHECK_REQUIRED")


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_EVIDENCE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise ValueError("evidence root must be an object")
        validate(raw)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"PHASE_08_EVIDENCE_INVALID: {error}", file=sys.stderr)
        return 1
    print("PHASE_08_EVIDENCE_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
