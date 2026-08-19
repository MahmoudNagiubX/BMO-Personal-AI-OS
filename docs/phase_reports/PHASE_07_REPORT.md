# Phase 7 Completion Report

## Outcome

PASS — PHASE 7 TEXT-FIRST CONVERSATION READY FOR INDEPENDENT REVIEW

Phase 7 is implemented on `phase-07/text-first-conversation-clients` from the exact Phase 6
merge base `eb069d2ed05b1692c69c5dd5e8e406d025e1635c`. The implementation commits are
`fe976429148a7c4bcc1641eb082ebd561fe12807`, the normal cancel/finalization recovery
`46fd83c4c768ca610426c3b76026a82a47632bb3`, and lifecycle/WebSocket recovery
`05ff7844428662c13098e63a3f2337d5616544ea`. Draft PR #17 targets `main` and remains unmerged.

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

## Lifecycle recovery

- The reconciliation gate makes one startup attempt, records deferred database failure without
  leaking driver details, retries with a fresh session before every Phase 7 operation, and blocks
  work until stale queued/running/cancel-requested runs are reconciled.
- Open WebSockets revalidate by credential/device/owner IDs and current scopes every 2 seconds and
  immediately before event delivery. Credential/device/owner revocation closes with 4401; scope or
  session loss closes with 4403. A dedicated receive task observes disconnects, ignores inbound
  application frames, and never cancels the run.
- `_emit()` locks the session row before allocating the next sequence. The PostgreSQL
  close/finalization race proof requires strict unique sequences, a truthful terminal run, and an
  assistant message iff success. Unexpected executor failures persist only generic
  `internal`/`executor_failed` state when the database is available; otherwise restart
  reconciliation remains authoritative.

## Validation and evidence

The complete validation suite includes Ruff, strict mypy, unit/API/client/evidence tests,
PostgreSQL migration and concurrency/security tests in authoritative CI, governance/secret checks,
pre-commit, and diff checks. Local validation passed with 368 tests and 11 PostgreSQL tests
deselected because no local PostgreSQL URL was configured. GitHub CI run 108 passed on exact
implementation commit `05ff7844428662c13098e63a3f2337d5616544ea`, including all 379 tests and
the migration upgrade/current/check and downgrade/re-upgrade cycle. The strict subordinate evidence is
`infrastructure/home_server/evidence/phase_07_text_conversation.json`, validated by
`scripts/phase_07/validate_evidence.py`. It records the tested implementation commit and
implementation CI separately from the required external final exact-head GitHub check; it never
self-attests a commit containing the evidence. Run 105 had one bounded PostgreSQL race regression;
the refresh-before-finalization repair was applied as a normal commit and run 106 passed.

No Phase 7 component was persistently deployed to VENOM. The Lenovo resource-admission gate,
sudo checkpoint, owner/device bootstrap, physical smoke, and migration of real data were not
invoked. Phase 5B model/tunnel behavior and historical evidence remain unchanged. Repository
rollback is a normal revert; any future real-data schema rollback requires an encrypted backup and
owner approval. Phase 8 is `NOT_STARTED`.

Final exact-head CI and draft PR details are intentionally maintained as external handoff facts
at closeout rather than fabricated inside the repository evidence.

READY_FOR_PHASE_7_INDEPENDENT_REVIEW
