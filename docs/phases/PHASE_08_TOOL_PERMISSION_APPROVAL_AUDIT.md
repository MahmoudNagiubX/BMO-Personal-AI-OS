# Phase 8 — Tool, permission, approval, and audit platform

## Boundary

This repository-only phase establishes the deterministic security platform that
will be required before any future tool execution. It does not deploy to VENOM,
start Phase 9, add a public API, or execute a real consequential action.

The existing `personal_ai_os.model_gateway.ModelGateway` remains the only model
boundary. Its `ToolProposal` is data only. The LLM cannot select risk, scopes,
approval policy, executor, sandbox, or verification behavior.

## Implemented contracts

- Static versioned descriptors define strict input/output schemas, risk,
  required scopes/capabilities, availability, budgets, rate limits, redaction,
  verification, reversal, and sandbox policy.
- Pydantic strict contracts reject unknown fields, coercion, and non-finite
  values. Validated arguments are canonical sorted JSON and are bound by a
  SHA-256 digest; changed arguments cannot execute.
- Phase 6 and Phase 7 scope vocabularies are preserved. Phase 8 adds only
  `tool.catalog.read`, `tool.request`, `approval.read`, `approval.decide`, and
  `audit.read`; wildcard scopes are unsupported.
- Read and reversible synthetic tools may be policy-allowed. Consequential and
  critical tools require exact owner approval with bounded TTL. Forbidden and
  unavailable tools deny before execution.
- Database row locks and unique idempotency authority protect approval consume,
  replay, cancellation, budgets, and concurrent requests. Observations are
  typed and verification failure is never reported as success.
- Audit rows are append-oriented, redacted, and contain digests rather than raw
  credentials, provider payloads, prompts, or model responses. Lifecycle events
  cover proposal, denial, approval, start, success, failure, expiry, and
  cancellation.
- The bounded agent adapter accepts at most three model proposals and submits
  them to the platform as data. It never calls an executor directly.

## Migration and rollback

Migration `20260819_0004` follows Phase 7 revision `20260819_0003` and creates
tool calls, permission decisions, approvals, observations, audit events, and
rate buckets. A normal Alembic downgrade returns to `20260819_0003`; rollback
uses a normal Git revert and preserves earlier phase evidence.

No persistent PostgreSQL/Core API or VENOM deployment is part of this phase.
Physical admission remains a separate owner-authorized decision.

## Acceptance

Unit tests cover strict contracts, static registry behavior, approval binding,
expiry/rejection, idempotency, budgets, availability, synthetic output and
verification failures, redaction, cancellation, and the bounded model-proposal
adapter. PostgreSQL integration coverage covers approval races, atomic consume,
cancel/approve races, idempotency conflicts, and budget limits. The sanitized
machine-readable acceptance record is
`infrastructure/home_server/evidence/phase_08_tool_permission_approval_audit.json`.
