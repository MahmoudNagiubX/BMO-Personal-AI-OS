"""Validate concrete sanitized Phase 7 text-conversation evidence."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE = ROOT / "infrastructure/home_server/evidence/phase_07_text_conversation.json"
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
FORBIDDEN_KEYS = {
    "authorization_header",
    "bearer",
    "credential",
    "raw_credential",
    "enrollment_code",
    "secret_hash",
    "credential_hash",
    "code_hash",
    "database_url",
    "raw_prompt",
    "raw_response",
    "provider_payload",
    "provider_json",
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
RUN_STATUSES = ["queued", "running", "cancel_requested", "succeeded", "failed", "cancelled"]
EVENT_TYPES = [
    "session.ready",
    "message.accepted",
    "run.queued",
    "run.started",
    "run.cancel_requested",
    "run.cancelled",
    "run.succeeded",
    "run.failed",
    "run.interrupted",
    "assistant.message.ready",
]
FINAL_EXACT_HEAD_CI_KEYS = {"required", "verification"}
LEGACY_FINAL_CI_KEYS = {
    "final_evidence_head_status",
    "final_evidence_validated_commit",
    "final_evidence_run_number",
}


def nested(data: Mapping[str, Any], path: str) -> Any:
    """Return a required nested field or raise a deterministic error."""

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


def require_positive_int(data: Mapping[str, Any], path: str) -> int:
    value = nested(data, path)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{path} must be a positive integer")
    return value


def require_nonempty_list(data: Mapping[str, Any], path: str) -> list[Any]:
    value = nested(data, path)
    if not isinstance(value, list) or not value:
        raise ValueError(f"{path} must be a non-empty list")
    return value


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
    """Reject summary-only claims that lack concrete Phase 7 proof."""

    reject_sensitive_keys(data)
    require_equal(data, "schema_version", "phase-07-text-conversation/v1")
    commit = nested(data, "tested_git_commit")
    if not isinstance(commit, str) or COMMIT_PATTERN.fullmatch(commit) is None:
        raise ValueError("tested_git_commit must be a full lowercase commit SHA")

    require_equal(data, "migration.revision", "20260819_0003")
    for field in ("upgrade", "downgrade_upgrade_cycle", "alembic_check"):
        require_equal(data, f"migration.{field}", "pass")

    require_equal(
        data,
        "domain.tables",
        [
            "conversations",
            "conversation_sessions",
            "conversation_messages",
            "agent_runs",
            "run_events",
        ],
    )
    require_equal(data, "domain.message_roles", ["user", "assistant"])
    require_equal(data, "domain.system_messages_durable", False)
    require_equal(data, "domain.message_content_max_chars", 4000)
    require_equal(data, "domain.ordinal_unique_per_conversation", True)
    require_equal(data, "domain.event_schema", "phase-07-event/v1")
    require_equal(data, "domain.event_types", EVENT_TYPES)
    require_equal(data, "domain.run_statuses", RUN_STATUSES)

    scopes = nested(data, "authorization")
    if not isinstance(scopes, Mapping):
        raise ValueError("authorization must be an object")
    if set(nested(data, "authorization.phase_6_scopes")) != PHASE_6_SCOPES:
        raise ValueError("authorization.phase_6_scopes must preserve Phase 6 vocabulary")
    if set(nested(data, "authorization.phase_7_scopes")) != PHASE_7_SCOPES:
        raise ValueError("authorization.phase_7_scopes must contain exactly Phase 7 scopes")
    if set(nested(data, "authorization.active_scopes")) != PHASE_6_SCOPES | PHASE_7_SCOPES:
        raise ValueError("authorization.active_scopes must be the Phase 6/7 union")
    require_equal(data, "authorization.new_enrollment_vocabulary", "phase_6_plus_phase_7")
    require_equal(data, "authorization.wildcard_supported", False)
    require_equal(data, "authorization.missing_scope_status", 403)
    require_equal(data, "authorization.owner_mutation_remote", False)

    require_equal(data, "idempotency.same_key_attempts", 2)
    require_equal(data, "idempotency.inserted_messages", 1)
    require_equal(data, "idempotency.replay_results", 1)
    require_equal(data, "idempotency.different_content_status", 409)
    require_equal(data, "idempotency.scope", "conversation_and_device")
    require_equal(data, "active_run.database_constraint", "partial_unique_per_conversation")
    require_equal(data, "active_run.race_attempts", 2)
    require_equal(data, "active_run.race_accepted", 1)
    require_equal(data, "active_run.race_busy", 1)
    require_equal(data, "active_run.statuses", RUN_STATUSES)

    endpoints = require_nonempty_list(data, "rest.endpoints")
    expected_endpoints = {
        "POST /api/v1/conversations",
        "GET /api/v1/conversations",
        "GET /api/v1/conversations/{conversation_id}",
        "GET /api/v1/conversations/{conversation_id}/messages",
        "POST /api/v1/conversations/{conversation_id}/sessions",
        "GET /api/v1/conversation-sessions/{session_id}",
        "POST /api/v1/conversation-sessions/{session_id}/close",
        "POST /api/v1/conversation-sessions/{session_id}/messages",
        "GET /api/v1/conversations/{conversation_id}/runs",
        "GET /api/v1/agent-runs/{run_id}",
        "POST /api/v1/agent-runs/{run_id}/cancel",
    }
    if set(endpoints) != expected_endpoints:
        raise ValueError("rest.endpoints must enumerate the bounded Phase 7 API")
    require_equal(data, "rest.authentication", "opaque_bearer_scopes")
    require_equal(data, "rest.owner_scoped_queries", True)
    require_equal(data, "rest.validation_errors_sanitized", True)

    require_equal(data, "websocket.path", "/api/v1/conversation-sessions/{session_id}/events")
    require_equal(data, "websocket.authentication", "authorization_header_only")
    require_equal(data, "websocket.missing_credential_status", 4401)
    require_equal(data, "websocket.missing_scope_status", 4403)
    require_equal(data, "websocket.replay_after_sequence", True)
    require_equal(data, "websocket.poll_interval_ms", 250)
    require_equal(data, "websocket.disconnect_does_not_cancel", True)
    require_equal(data, "websocket.envelope_schema", "phase-07-event/v1")
    require_equal(data, "websocket.sequence_strictly_increasing", True)

    require_equal(data, "reconciliation.startup_attempted", True)
    require_equal(data, "reconciliation.startup_failure_deferred", True)
    require_equal(data, "reconciliation.retry_before_operation", True)
    require_equal(data, "reconciliation.fresh_session_per_attempt", True)
    require_equal(data, "reconciliation.single_attempt_at_a_time", True)
    require_equal(data, "reconciliation.unavailable_http_status", 503)
    require_equal(data, "reconciliation.unavailable_websocket_code", 1013)
    require_equal(data, "reconciliation.stale_statuses", RUN_STATUSES[:3])
    require_equal(data, "reconciliation.stale_failure_code", "server_restart_interrupted")
    require_equal(data, "reconciliation.stale_before_operation", True)
    require_equal(data, "reconciliation.error_detail_redacted", True)

    require_equal(data, "websocket.revalidation.cadence_seconds", 2.0)
    require_equal(data, "websocket.revalidation.uses_identity_ids", True)
    require_equal(data, "websocket.revalidation.rehashes_secret", False)
    require_equal(data, "websocket.revalidation.credential_revoked_code", 4401)
    require_equal(data, "websocket.revalidation.device_revoked_code", 4401)
    require_equal(data, "websocket.revalidation.owner_disabled_code", 4401)
    require_equal(data, "websocket.revalidation.scope_loss_code", 4403)
    require_equal(data, "websocket.revalidation.session_loss_code", 4403)
    require_equal(data, "websocket.revalidation.no_event_after_reject", True)
    require_equal(data, "websocket.disconnect_observer.explicit_receive_task", True)
    require_equal(data, "websocket.disconnect_observer.idle_poll_stops", True)
    require_equal(data, "websocket.disconnect_observer.inbound_frames_ignored", True)
    require_equal(data, "websocket.disconnect_observer.no_cancellation", True)

    require_equal(data, "event_sequence.session_row_lock", "FOR UPDATE")
    require_equal(data, "event_sequence.close_finalization_postgresql_race", "pass")
    require_equal(data, "event_sequence.no_integrity_error", True)
    require_equal(data, "event_sequence.unique_and_strict", True)
    require_equal(data, "event_sequence.terminal_after_race", True)
    require_equal(data, "event_sequence.assistant_iff_succeeded", True)

    require_equal(data, "executor.exception_boundary", True)
    require_equal(data, "executor.failure_category", "internal")
    require_equal(data, "executor.failure_code", "executor_failed")
    require_equal(data, "executor.terminal_untouched", True)
    require_equal(data, "executor.db_unavailable_deferred_to_reconciliation", True)
    require_equal(data, "executor.raw_exception_persisted", False)

    require_equal(data, "gateway.boundary", "personal_ai_os.model_gateway.ModelGateway")
    require_equal(data, "gateway.direct_ollama_from_conversation_code", False)
    require_equal(data, "gateway.provider_bypass", False)
    require_equal(data, "gateway.capability", "chat")
    require_equal(data, "gateway.model_id", "qwen3.5:4b")
    require_equal(data, "gateway.context_tokens", 4096)
    require_equal(data, "gateway.max_output_tokens", 256)
    require_equal(data, "gateway.tools_requested", False)
    require_equal(data, "gateway.tool_execution", False)
    require_equal(data, "gateway.cloud_fallback", False)
    require_equal(data, "gateway.response_identity_verified", True)
    require_equal(data, "gateway.response_request_id_verified", True)

    require_equal(data, "context.max_history_messages", 16)
    require_equal(data, "context.max_history_chars", 6000)
    require_equal(data, "context.current_message_preserved", True)
    require_equal(data, "context.truncation_recorded", True)
    require_equal(data, "context.system_instruction_text_only_no_tools", True)

    require_equal(data, "execution.queued_to_running", True)
    require_equal(data, "execution.gateway_call_outside_db_lock", True)
    require_equal(data, "execution.assistant_written_only_after_verified_success", True)
    require_equal(data, "execution.failed_run_has_no_assistant", True)
    require_equal(data, "execution.cancel.queued_terminal_cancelled", True)
    require_equal(data, "execution.cancel.running_cancel_requested", True)
    require_equal(data, "execution.cancel.finalization_truthful", True)
    require_equal(data, "execution.cancel.race", "cancelled_without_assistant")
    require_equal(
        data,
        "execution.restart.orphan_statuses",
        ["queued", "running", "cancel_requested"],
    )
    require_equal(data, "execution.restart.failure_code", "server_restart_interrupted")
    require_equal(data, "execution.restart.reconciled_before_acceptance", True)

    require_equal(data, "trace.persisted_events_sanitized", True)
    require_equal(data, "trace.persisted_provider_payload", False)
    require_equal(data, "trace.persisted_prompt_or_response_content", False)
    require_equal(data, "trace.assistant_content_source", "verified_generation_response")
    require_equal(data, "trace.assistant_message_run_link", True)
    require_equal(data, "trace.lifecycle_event_run_link", True)

    require_equal(data, "client.path", "scripts/phase_07/text_client.py")
    require_equal(
        data,
        "client.credential_sources",
        ["BMO_DEVICE_CREDENTIAL", "BMO_DEVICE_CREDENTIAL_FILE"],
    )
    require_equal(data, "client.credential_in_argv", False)
    require_equal(data, "client.websocket_streaming", True)
    require_equal(data, "client.cancel_command", True)
    require_equal(data, "client.reconnect_cursor", True)

    require_equal(data, "tests.unit_api_client", "pass")
    require_equal(data, "tests.postgresql_concurrency_security", "pass")
    require_positive_int(data, "tests.unit_count")
    require_positive_int(data, "tests.integration_count")
    require_equal(data, "security.no_public_or_lan_api", True)
    require_equal(data, "security.no_content_logging", True)
    require_equal(data, "security.phase_5b_behavior_preserved", True)
    require_equal(data, "rollback.normal_revert", True)
    require_equal(data, "phase_8", "NOT_STARTED")

    require_equal(data, "ci.implementation_status", "success")
    require_equal(data, "ci.implementation_exact_commit", commit)
    require_positive_int(data, "ci.implementation_run_number")
    ci = nested(data, "ci")
    if not isinstance(ci, Mapping):
        raise ValueError("ci must be an object")
    if LEGACY_FINAL_CI_KEYS.intersection(ci):
        raise ValueError("ci must not self-attest final exact-head commit/status/run")
    final_ci = nested(data, "ci.final_exact_head_ci")
    if not isinstance(final_ci, Mapping) or set(final_ci) != FINAL_EXACT_HEAD_CI_KEYS:
        raise ValueError("ci.final_exact_head_ci must contain only required and verification")
    require_equal(data, "ci.final_exact_head_ci.required", True)
    require_equal(
        data,
        "ci.final_exact_head_ci.verification",
        "EXTERNAL_GITHUB_CHECK_REQUIRED",
    )

    require_equal(data, "venom_deployment.performed", False)
    require_equal(data, "venom_deployment.resource_admission", "NOT_REQUIRED_REPOSITORY_ONLY")


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_EVIDENCE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("evidence root must be an object")
        validate(payload)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Phase 7 evidence validation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print("Phase 7 text conversation evidence validation passed.")


if __name__ == "__main__":
    main()
