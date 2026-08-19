# Phase 7 Completion Report

## Outcome

PASS — PHASE 7 TEXT-FIRST CONVERSATION READY FOR INDEPENDENT REVIEW

Phase 7 is implemented on `phase-07/text-first-conversation-clients` from the exact Phase 6
merge base `eb069d2ed05b1692c69c5dd5e8e406d025e1635c`. The final exact head and draft PR are
recorded after the normal implementation and evidence commits are pushed. The PR remains draft
and is not merged.

## Repository and schema

- Migration revision: `20260819_0003`; it creates conversations, device-bound sessions,
  bounded messages, agent runs, and sanitized replay events.
- Run states are queued, running, cancel_requested, succeeded, failed, and cancelled.
- Message ordinals are unique per conversation; only user and verified assistant messages are
  durable; system instructions are request context only.
- Phase 6 scopes remain intact. New enrollments may use only the explicit Phase 7 additions:
  `conversation.read`, `conversation.write`, `conversation.stream`, and
  `conversation.run.cancel`. No wildcard or implicit authority exists.

## Interfaces and execution

- REST provides owner/device-scoped conversation, session, message, run-history, and cancel
  operations under `/api/v1`.
- WebSocket `/api/v1/conversation-sessions/{session_id}/events` accepts bearer credentials only
  in the Authorization header, uses 4401/4403 authentication boundaries, replays by sequence,
  and emits `phase-07-event/v1` events with bounded polling.
- UUID idempotency is per authenticated device and conversation. Same-content replay returns the
  original run; different content is a typed 409 conflict. A PostgreSQL partial unique index and
  concurrent tests enforce one active run per conversation.
- Every generation request crosses `personal_ai_os.model_gateway.ModelGateway` with Qwen3.5 4B,
  `Capability.CHAT`, context 4096, max output 256, and `tools=()`. Conversation code does not
  call Ollama directly, bypass the gateway, execute tools, or use cloud fallback.
- Queued cancellation is terminal `cancelled`; running cancellation is first
  `cancel_requested`, and provider finalization converts it truthfully to `cancelled` without an
  assistant message. Startup reconciliation fails orphaned runs with
  `server_restart_interrupted`.
- Assistant content is persisted only after request-ID, model identity/digest, usage, and typed
  response validation. Persisted events contain no credentials, authorization data, provider
  JSON, raw prompt/response, or chain-of-thought.
- `scripts/phase_07/text_client.py` is a minimal authenticated client using an environment
  variable or protected local credential file, real WebSocket event replay, history, reconnect
  cursor, active `/cancel`, and truthful detach behavior.

## Validation and evidence

The complete validation suite includes Ruff, strict mypy, unit/API/client/evidence tests,
PostgreSQL migration and concurrency/security tests in authoritative CI, governance/secret checks,
pre-commit, and diff checks. The strict subordinate evidence is
`infrastructure/home_server/evidence/phase_07_text_conversation.json`, validated by
`scripts/phase_07/validate_evidence.py`. It records the tested implementation commit and
implementation CI separately from the required external final exact-head GitHub check; it never
self-attests a commit containing the evidence.

No Phase 7 component was persistently deployed to VENOM. The Lenovo resource-admission gate,
sudo checkpoint, owner/device bootstrap, physical smoke, and migration of real data were not
invoked. Phase 5B model/tunnel behavior and historical evidence remain unchanged. Repository
rollback is a normal revert; any future real-data schema rollback requires an encrypted backup and
owner approval. Phase 8 is `NOT_STARTED`.

Final exact-head CI and draft PR details are intentionally maintained as external handoff facts
at closeout rather than fabricated inside the repository evidence.

READY_FOR_PHASE_7_INDEPENDENT_REVIEW
