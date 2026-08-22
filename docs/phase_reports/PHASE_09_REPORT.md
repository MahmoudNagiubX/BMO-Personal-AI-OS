# Phase 9 Windows Satellite Report

## Outcome

The previously accepted repository/software and complete physical hardware gate remain preserved on tested implementation commit `e1514533db08fa7c25b3db353e0d8df0be0dbf85`. The earlier targeted operations blocker was caused by a stale VENOM address (`192.162.1.21`). VENOM was subsequently verified as `venom-server` at `192.162.1.25`, and the exact recovery release was deployed and tested there.

Following authorized prerequisite deployment of the accepted Phase 6–8 Core API authority and private PostgreSQL stack on VENOM (`192.162.1.25`), the historical Phase 9 Windows Satellite physical test suite remains preserved with all 14 physical acceptance criteria passed. This recovery did not rerun that hardware gate. It tested the exact operational candidate, encrypted backup/restore, and deterministic rollback. The final durable VENOM release and schema were restored to the accepted baseline `24297a9c8ce8ce8d386874949aa3d87e0881d9cc` / `20260820_0005`.

## Implemented Boundary

- Protocol `phase-09-windows-satellite/v1` uses one authenticated TUF-to-VENOM outbound WebSocket, 16 KiB frames, 15-second heartbeat, two in-flight commands, duplicate-session rejection, per-frame principal revalidation, exact digest/deadline/capability binding, and capped reconnect backoff.
- The reusable opaque credential is stored under a fixed current-user Windows Credential Manager target (`BMO/WindowsSatellite/credential`). Enrollment and rotation never write it to config, task arguments, logs, environment variables, or Git.
- Phase 8 remains the sole request, risk, permission, approval, budget, idempotency, execution-transition, and audit authority. Executor routing is selected only by the immutable descriptor.
- The strict local JSON allowlist accepts stable IDs, absolute local paths, fixed argument arrays, bounded search roots, and exact workflow verification. It rejects unknown fields, duplicate keys/IDs, relative/UNC/expanded paths, newline/NUL arguments, ambiguous PowerShell pairing, and workflow escape.
- The current-user scheduled task uses an at-logon interactive trigger and limited run level. Lifecycle helpers create no service, listener, firewall rule, administrator requirement, or unrelated process cleanup.
- Operational support for persistent private authority deployment, systemd units, backup/restore verification, health monitoring, and release deployment/rollback is committed under `infrastructure/home_server/`. Release identity is mandatory and exact, secret permissions fail closed, and rollback requires the explicit `/health/model-gateway` readiness contract.

## Targeted Operations Recovery

- Stale-address correction: the previous `192.162.1.21` result was not a host failure; that address was stale. Read-only identity checks confirmed `192.162.1.25` is `venom-server`, user `venom`, Ubuntu 24.04.4 x86_64, with the existing Phase 5B and Core deployment layout.
- Operations tested commit: `f12de5a9c0927b657086aa53175ad5224baaefba`.
- Candidate release acceptance: PASS — exact clean Git identity, deterministic `uv sync --frozen --no-dev`, effective `0600` config/passphrase files, pinned PostgreSQL image content digest, loopback PostgreSQL, migration `20260820_0006`, Core readiness/version, and `/health/model-gateway` ready.
- Encrypted backup and restore verification: PASS — SHA-256 verified and temporary restore reached schema `20260820_0006`.
- Rollback: exact baseline identity, migration `20260820_0005`, Core readiness/version, and private listeners passed. The explicit `/health/model-gateway` rollback check returned HTTP 404 because the accepted baseline release does not contain that route.
- Targeted VENOM result: `BLOCKED_ROLLBACK_BASELINE_MODEL_GATEWAY`.
- Precise blocker: `ACCEPTED_BASELINE_MISSING_MODEL_GATEWAY_ROUTE`. The baseline was left active and no compatibility route or baseline commit alteration was introduced.
- The historical Windows implementation commit remains `e1514533db08fa7c25b3db353e0d8df0be0dbf85`; the Windows hardware gate was not rerun.

## Tool Catalog & Physical Metrics

| Tool | Risk | Approval | Physical Gate Latency | Verification Result |
|---|---|---|---|---|
| `windows.status.read` | read | none | 402.1 ms | CPU=9.8%, RAM=81.6%, Disk=94.5%, finite scalars |
| `windows.files.search` | read | none | 309.2 ms | 5 matches found beneath allowlisted root, metadata-only |
| `windows.app.open` | reversible | none | 508.4 ms | Notepad launched with `shell=False`, process observed |
| `windows.project.open` | reversible | none | 531.0 ms | BMO Core project directory verified on disk |
| `windows.media.volume.get` / `set` | read / reversible | none | 450.0 ms | Initial 54% -> Set 45% (measured 45%) -> Restored 54% |
| `windows.workflow.start` | consequential | exact owner | 836.4 ms | Owner approved, marker verified on disk |

## Physical Proof Highlights

1. **Real End-to-End In-Flight Workflow Cancellation**:
   - Consequential workflow started with owner approval.
   - Child process (`powershell.exe`, PID 34024) observed running under satellite.
   - Core API received `POST /api/v1/tool-calls/{id}/cancel`, transition to `cancel_requested` logged.
   - `CancelCommand` delivered over WebSocket channel; satellite terminated owned child process.
   - Observation returned `status: cancelled`, completion marker was NOT created on disk.
   - Core persisted `cancelled` state; audit trail confirmed `tool.cancel_requested` and `tool.cancelled`.
2. **Physical Replay / Duplicate Proofs**:
   - Replay of identical command ID + argument digest returned cached observation; side effect count remained 1 (no duplicate execution).
   - Tampered argument digest for existing command ID failed closed with `replay_digest_mismatch`.
   - Interrupted consequential command journal recovery failed closed with `consequential_outcome_uncertain`.
3. **Live Satellite Revocation Proof**:
   - Temporary satellite device enrolled and connected.
   - Device revoked via Core API `IdentityService.revoke_device` on VENOM.
   - Open WebSocket transport rejected on frame revalidation; admin/owner access remained unaffected.
4. **Transport & Network Verification**:
   - Physical test transport: `ws_loopback_over_authenticated_ssh_forward` (Core API `127.0.0.1:8000`, PostgreSQL `127.0.0.1:5432`).
   - Production transport contract: `wss` (enforced for non-loopback connections).
   - Zero inbound listening ports on TUF (satellite operates purely outbound).
   - Satellite idle resources: 0.0% CPU, 5.0 MB RAM.

## Post-Test VENOM Baseline Restoration

VENOM durable state was cleanly rolled back to accepted main baseline:
- Commit SHA: `24297a9c8ce8ce8d386874949aa3d87e0881d9cc`
- Alembic Schema: `20260820_0005`
- Service `bmo-core.service`: active and healthy (`/health/ready` -> 200 OK, `/version` -> build_sha: `24297a9c8ce8ce8d386874949aa3d87e0881d9cc`)
- PostgreSQL 16 container: healthy and bound exclusively to `127.0.0.1:5432`
- Model Tunnel & Ollama: loopback-only 4B/BGE runtime was started and verified for candidate acceptance; the accepted baseline remains active after rollback.

## Evidence & Governance

Sanitized structured evidence is recorded in `docs/phase_reports/evidence/PHASE_09_WINDOWS_SATELLITE.json` and validated by `scripts/phase_09/validate_evidence.py`. `tested_implementation_commit` remains locked at `e1514533db08fa7c25b3db353e0d8df0be0dbf85`; `operations_tested_commit` records the exact physically tested candidate `f12de5a9c0927b657086aa53175ad5224baaefba`. The overall targeted gate remains blocked because the accepted rollback baseline lacks the explicit model-gateway route required by the hardened rollback contract.

Phase 10 = `NOT_STARTED`.
