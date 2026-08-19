# Phase 8 threat model — deterministic tool authority

This threat model covers the repository-only Phase 8 platform. Real tools and
physical deployment are outside this phase.

| Asset | Attacker/precondition and attack path | Impact | Preventive control | Detective control | Fail-closed behavior | Test/evidence | Residual/future phase |
|---|---|---|---|---|---|---|---|
| Static risk policy | Model or client submits a caller-selected risk/policy | Consequential action is disguised as read | Registry owns immutable descriptors; request schema has no risk field | Decision row records descriptor risk | Unknown or mismatched descriptor is denied | Registry mutation tests; `registry.risk_source` | Independent review before real tools |
| Input binding | Client changes arguments after approval | Approved action executes different data | Strict validation plus canonical SHA-256 digest | Approval and call retain digest | Digest mismatch denies execution | TOCTOU unit test | Real tools need typed adapters |
| Approval authority | Non-owner device approves or replays an approval | Unauthorized consequential action | Owner/device binding, exact scopes, row lock, TTL | Approval lifecycle audit | Wrong owner/status/expiry is rejected | PostgreSQL approve/reject and replay races | Owner UX is later work |
| Concurrent consume | Two workers consume one approval | Duplicate side effect | `SELECT FOR UPDATE`, consumed state, execution idempotency | Start/success audit count | One terminal authority winner | PostgreSQL consume race | Real executor must also be idempotent |
| Cancellation race | Cancel arrives while approval or execution starts | False cancellation or resurrection | Locked state transitions; executing operation is not falsely cancelled | Cancel/start lifecycle events | Terminal calls cannot be revived | PostgreSQL approval/cancel race | Cooperative cancellation per satellite later |
| Idempotency | Same key is reused with different arguments or concurrent inserts | Duplicate or confused action | Unique owner/device/tool/key and digest comparison | Conflict audit | Different digest is 409/deny | PostgreSQL same/different key race | Per-tool external idempotency later |
| Budget/rate abuse | Client floods proposals or concurrent execution | Resource exhaustion | Run proposal/execution/approval limits and fixed rate policy | Durable counts and audit | Budget exhaustion blocks new work | PostgreSQL budget/rate coverage | Per-device operational tuning later |
| Availability spoofing | Offline/degraded provider is claimed available | Action runs without dependency | Availability is platform input, not model output | Decision reason records state | Offline is denied; degraded requires explicit safe policy | Offline unit proof | Health integration later |
| Executor escape | A tool implementation exposes shell or raw request data | Arbitrary host compromise | Typed executor request and synthetic-only catalog; forbidden sandbox | Output/verification and audit boundary | No executor is registered for forbidden policy | Shell absence and boundary tests | Satellite sandboxes require ADR |
| Output forgery | Executor returns malformed or unverified output | False success or unsafe downstream state | Strict output model and verification policy | Failed observation and failure code | Invalid/unverified output is failed | Output/verification tests | External systems need independent verification |
| Audit leakage/tampering | Logs include secrets or rows are edited | Credential/privacy compromise or loss of evidence | Digest-only redacted metadata and append-oriented rows | Audit lifecycle query | Audit failure blocks consequential requests | Sensitive-key validator and audit tests | Immutable external storage is future hardening |
| API scope confusion | Device uses Phase 6/7 scopes as Phase 8 authority | Unauthorized catalog/approval/audit access | Explicit Phase 8 scopes; no wildcard | Authenticated route tests | Missing scope returns 403 | Scope vocabulary evidence | UI permission presentation later |
| Agent loop escalation | Model emits repeated tool proposals | Unbounded action loop | Adapter cap of three proposals; approval pauses | Proposal count and run budget | Excess proposals are truncated/blocked | Agent runtime test | Phase 9 agents remain unstarted |
| Evidence self-attestation | Evidence claims final CI for its own commit | Governance bypass | Implementation evidence and external exact-head sentinel separated | Strict validator rejects legacy fields | Final state remains review-required | Evidence validator mutants | Owner merges only after external check |

## Security acceptance

The implementation uses synthetic executors only, keeps Ollama and PostgreSQL
deployment unchanged, adds no public/LAN listener, stores no reusable plaintext
credential, and does not begin Phase 9.
