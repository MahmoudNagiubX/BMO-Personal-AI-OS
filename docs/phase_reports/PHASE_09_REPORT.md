# Phase 9 Windows Satellite Report

## Outcome

Repository/software acceptance and complete physical hardware acceptance gate are PASSED on tested implementation commit `e1514533db08fa7c25b3db353e0d8df0be0dbf85`.

Following authorized prerequisite deployment of the accepted Phase 6–8 Core API authority and private PostgreSQL stack on VENOM (`192.162.1.21`), the full Phase 9 Windows Satellite physical test suite executed live across the VENOM control plane and ASUS TUF execution node. All 14 physical acceptance criteria passed with zero crashes, zero errors, zero inbound listeners on TUF, verified in-flight cancellation, verified replay deduplication, verified live device revocation, and clean rollback of VENOM to accepted production baseline `24297a9c8ce8ce8d386874949aa3d87e0881d9cc` (schema `20260820_0005`).

## Implemented Boundary

- Protocol `phase-09-windows-satellite/v1` uses one authenticated TUF-to-VENOM outbound WebSocket, 16 KiB frames, 15-second heartbeat, two in-flight commands, duplicate-session rejection, per-frame principal revalidation, exact digest/deadline/capability binding, and capped reconnect backoff.
- The reusable opaque credential is stored under a fixed current-user Windows Credential Manager target (`BMO/WindowsSatellite/credential`). Enrollment and rotation never write it to config, task arguments, logs, environment variables, or Git.
- Phase 8 remains the sole request, risk, permission, approval, budget, idempotency, execution-transition, and audit authority. Executor routing is selected only by the immutable descriptor.
- The strict local JSON allowlist accepts stable IDs, absolute local paths, fixed argument arrays, bounded search roots, and exact workflow verification. It rejects unknown fields, duplicate keys/IDs, relative/UNC/expanded paths, newline/NUL arguments, ambiguous PowerShell pairing, and workflow escape.
- The current-user scheduled task uses an at-logon interactive trigger and limited run level. Lifecycle helpers create no service, listener, firewall rule, administrator requirement, or unrelated process cleanup.
- Operational support for persistent private authority deployment, systemd units, backup/restore verification, health monitoring, and release deployment/rollback is committed under `infrastructure/home_server/`.

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
- Model Tunnel & Ollama: active and verified (Qwen 2.5 / 3.5 4B, BGE-M3 embeddings, Advanced Gateway routes intact)

## Evidence & Governance

Sanitized structured evidence is recorded in `docs/phase_reports/evidence/PHASE_09_WINDOWS_SATELLITE.json` and validated by `scripts/phase_09/validate_evidence.py`. Tested implementation commit is locked at `e1514533db08fa7c25b3db353e0d8df0be0dbf85`. Subsequent documentation, operations tooling, and evidence commits remain strictly ahead in git history without modifying `tested_implementation_commit`.

Phase 10 = `NOT_STARTED`.
