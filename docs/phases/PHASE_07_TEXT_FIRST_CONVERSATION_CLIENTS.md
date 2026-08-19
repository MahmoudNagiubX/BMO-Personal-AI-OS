# Phase 7 — Text-First Conversation Clients

## Status

Implemented on `phase-07/text-first-conversation-clients` from the exact Phase 6 merge
commit `eb069d2ed05b1692c69c5dd5e8e406d025e1635c`; awaiting independent review on a draft
pull request. Phase 8 is `NOT_STARTED`.

Phase 7 is repository-only in this acceptance step. No persistent Core API or PostgreSQL
deployment has been performed on VENOM, so the Lenovo resource-admission gate is not invoked.

## Scope

Phase 7 adds durable text conversations, device-bound sessions, authenticated REST and
WebSocket boundaries, idempotent submissions, one active run per conversation, truthful
cancellation, restart reconciliation, verified response traces, and a minimal authenticated
terminal text client. It does not add tools, tool execution, approvals, memory/RAG, voice,
Flutter clients, public network exposure, or Phase 8 behavior.

All generation requests cross `personal_ai_os.model_gateway.ModelGateway` with capability
`chat`. The accepted Qwen3.5 4B identity is verified on the response. The conversation package
does not import or call Ollama directly, does not bypass the gateway, does not request tools, and
does not provide cloud fallback. Output is bounded to a 4,096-token context and 256 output
tokens.

## Durable model and state rules

The `20260819_0003` migration creates `conversations`, `conversation_sessions`,
`conversation_messages`, `agent_runs`, and `run_events`. User and verified assistant messages
are bounded to 4,000 characters and have unique conversation ordinals. System instructions are
request context only and are not durable messages. Assistant content is written only after a
typed, request-matched, Qwen-identity-matched successful `GenerationResponse`.

Run states are `queued`, `running`, `cancel_requested`, `succeeded`, `failed`, and `cancelled`.
A partial unique database index permits at most one non-terminal run per conversation. A
client-supplied UUID is unique per authenticated device and conversation: identical replays
return the original message/run, while different content returns a typed conflict.

Context assembly is deterministic: the current user message is retained, at most 16 recent
messages and approximately 6,000 characters are sent, and truncation is recorded on the run.
The gateway call occurs outside database locks in a fresh executor session.

## Lifecycle and WebSocket recovery

Startup reconciliation is a serialized fail-closed gate. A transient database failure records a
deferred state without exposing the database error, and every Phase 7 REST or WebSocket operation
retries reconciliation with a fresh session before work. Until it succeeds, REST returns generic
503 and a WebSocket is rejected with 1013; queued, running, and cancel-requested stale runs are
reconciled before a new operation is accepted.

An accepted WebSocket revalidates the credential, device, owner, current scopes, and active session
by identity IDs every 2 seconds and immediately before delivering a replay batch. Credential,
device, or owner loss closes with 4401; scope or session loss closes with 4403, with no protected
event sent after rejection. A dedicated ASGI receive task observes disconnects and safely ignores
inbound application frames; disconnect never cancels or mutates a run.

RunEvent sequence allocation locks the session row with `FOR UPDATE` before MAX+1 allocation,
including close/finalization races. The executor has a bounded sanitized exception boundary that
persists `internal`/`executor_failed` when possible and leaves database-unavailable work for
restart reconciliation. The PostgreSQL race and deterministic lifecycle proofs are part of the
Phase 7 test suite. A parameterized real-PostgreSQL proof covers `queued`, `running`, and
`cancel_requested` persisted runs after a deferred first reconciliation attempt: a fresh session
retry marks each stale run `failed` with `interrupted`/`server_restart_interrupted`, releases the
active-run constraint, and accepts a new message/run without changing the stale result.

## Authorization and interfaces

Phase 6 scopes remain unchanged. New enrollments may use the explicit Phase 7 union:

- `conversation.read`
- `conversation.write`
- `conversation.stream`
- `conversation.run.cancel`

There is no wildcard or implicit authority. Conversations, sessions, messages, runs, and event
replay are owner- and creating-device-scoped. Missing credentials return generic HTTP 401;
missing scopes return 403. The WebSocket accepts bearer credentials only in the Authorization
header, closes unauthenticated clients with 4401 and unauthorized clients with 4403, replays
after `after_sequence`, and polls at a bounded interval. Disconnecting does not cancel a run.

The REST surface is:

```text
POST /api/v1/conversations
GET  /api/v1/conversations
GET  /api/v1/conversations/{conversation_id}
GET  /api/v1/conversations/{conversation_id}/messages
POST /api/v1/conversations/{conversation_id}/sessions
GET  /api/v1/conversation-sessions/{session_id}
POST /api/v1/conversation-sessions/{session_id}/close
POST /api/v1/conversation-sessions/{session_id}/messages
GET  /api/v1/conversations/{conversation_id}/runs
GET  /api/v1/agent-runs/{run_id}
POST /api/v1/agent-runs/{run_id}/cancel
WS   /api/v1/conversation-sessions/{session_id}/events
```

Lifecycle events use `phase-07-event/v1`, strictly increasing session sequence numbers, and
sanitized payloads: `session.ready`, `message.accepted`, `run.queued`, `run.started`,
`run.cancel_requested`, `run.cancelled`, `run.succeeded`, `run.failed`, `run.interrupted`, and
`assistant.message.ready`. Persisted events contain identifiers and bounded state, never raw
credentials, authorization data, provider JSON, prompts, responses, or chain-of-thought.

## Recovery and client

At application startup, orphaned `queued`, `running`, and `cancel_requested` runs are marked
`failed` with `server_restart_interrupted` and a sanitized reconciliation event. A queued cancel
is terminal `cancelled`; a running cancel first becomes `cancel_requested`, and finalization
records `cancelled` if the provider response arrives after that request. Failed or cancelled runs
never receive assistant messages.

`scripts/phase_07/text_client.py` loads an opaque credential only from
`BMO_DEVICE_CREDENTIAL` or an owner-readable `BMO_DEVICE_CREDENTIAL_FILE`; it never accepts a
credential as an argument or prints it. It creates or selects a conversation, opens a session,
submits text with a UUID idempotency key, consumes real persisted lifecycle events, supports
history, reconnect cursor state, `/cancel` during an active run, and `/quit` without claiming a
server-side cancellation.

## Acceptance boundary

The complete repository validation and PostgreSQL path are authoritative for acceptance. The
machine-readable subordinate evidence is in
`infrastructure/home_server/evidence/phase_07_text_conversation.json`, enforced by
`scripts/phase_07/validate_evidence.py`. The latest implementation proof passed 371 local
non-PostgreSQL tests and all 385 authoritative CI tests, including 14 PostgreSQL cases. Its implementation CI fields identify the tested
implementation commit; final exact-head GitHub CI remains an external governance check and is
never self-attested by the evidence commit.

Phase 5B model/tunnel behavior remains preserved. Phase 8 is `NOT_STARTED`.
