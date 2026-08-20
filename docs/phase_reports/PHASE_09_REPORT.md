# Phase 9 Windows satellite report

## Outcome

Repository/software acceptance is complete for tested implementation commit
`7720c604181ec513729ff5a504a98a7eadc74772`. The required real TUF/VENOM tool
gate is `BLOCKED_PREREQUISITE`: read-only VENOM inspection found the accepted
Phase 5B release but no deployed Phase 6, Phase 7, or Phase 8 authority stack,
no Core API service/process/listener, and inactive PostgreSQL. The Phase 9
specification forbids silently deploying those missing historical production
phases, so the Windows satellite was not enrolled or installed and no physical
tool result is represented as passing.

## Implemented boundary

- Protocol `phase-09-windows-satellite/v1` uses one authenticated TUF-to-VENOM
  outbound WebSocket, 16 KiB frames, 15-second heartbeat, two in-flight
  commands, duplicate-session rejection, per-frame principal revalidation,
  exact digest/deadline/capability binding, and capped reconnect backoff.
- The reusable opaque credential is stored under a fixed current-user Windows
  Credential Manager target. Enrollment and rotation never write it to config,
  task arguments, logs, environment variables, or Git.
- Phase 8 remains the sole request, risk, permission, approval, budget,
  idempotency, execution-transition, and audit authority. Executor routing is
  selected only by the immutable descriptor.
- The strict local JSON allowlist accepts stable IDs, absolute local paths,
  fixed argument arrays, bounded search roots, and exact workflow verification.
  It rejects unknown fields, duplicate keys/IDs, relative/UNC/expanded paths,
  newline/NUL arguments, ambiguous PowerShell pairing, and workflow escape.
- The current-user scheduled task uses an at-logon interactive trigger and
  limited run level. Lifecycle helpers create no service, listener, firewall
  rule, administrator requirement, or unrelated process cleanup.

## Tool catalog

| Tool | Risk | Approval | Local verification |
|---|---|---|---|
| `windows.status.read` | read | none | Fresh finite bounded scalar telemetry |
| `windows.files.search` | read | none | Metadata only within canonical approved root |
| `windows.app.open` | reversible | none | Exact fixed process dispatch |
| `windows.project.open` | reversible | none | Exact fixed app and canonical project target |
| `windows.media.volume.get` | read | none | Core Audio measured readback |
| `windows.media.volume.set` | reversible | none | Requested/measured value within one percent |
| `windows.workflow.start` | consequential | exact owner | Expected exit and fixed marker verification |

No caller can supply an executable, process arguments, filesystem root, raw
path, PID, risk, approval policy, executor, PowerShell body, or allowlist
mutation. Every subprocess call uses `shell=False`. Workflow cancellation
tracks and stops only the child owned by the exact command ID; interrupted
consequential replay returns an honest uncertain outcome instead of retrying.

## Validation and tests

The exact implementation commit passed:

- `uv run python scripts/check.py`: 465 non-integration tests passed, 36
  PostgreSQL tests deselected because no local test database URL was set;
  Ruff lint/format, strict mypy, governance, and secret guard passed.
- Windows PowerShell parser: all three lifecycle scripts passed.
- Windows Credential Manager boundary: fixed product target was readable and
  no pre-existing Phase 9 credential was present; no credential was created.
- Focused Phase 9 coverage proves protocol/auth failures, wrong scope/device,
  disabled owner, revocation of an open socket, malformed/duplicate/oversized
  frames, duplicate sessions, digest/deadline/capability binding, offline
  denial, immutable policy, strict allowlists, metadata-only bounded search,
  finite telemetry, exact app/project dispatch, workflow verification,
  timeout/cancellation, replay uncertainty, no inbound/firewall surface, and
  Phase 10 exclusion.

Migration `20260820_0006` adds only the durable `cancel_requested` tool-call
state and downgrades to the Phase 8 constraint at `20260820_0005`. Local Docker
was unavailable, so upgrade/downgrade and all existing PostgreSQL atomicity
tests remain mandatory exact-head GitHub CI work, not a local pass claim.

## Physical prerequisite and deferred acceptance

Read-only key-authenticated inspection observed:

- accepted Phase 5B release link present;
- Phase 6, Phase 7, and Phase 8 deployment directories absent;
- PostgreSQL inactive;
- no Core API unit, exact process, or expected listener.

Therefore connection, telemetry, file search, app/project launch, volume
get/set/restore, exact workflow approval/execution, workflow cancellation,
offline/recovery, normal-user auto-start, idle CPU/RAM, latency, error, and
crash measurements are all `NOT_RUN_PREREQUISITE`. No sudo, server mutation,
credential issuance, satellite task installation, listener, or firewall
change was attempted.

Once the owner separately authorizes and accepts persistent Phase 6/7/8 Core
API and PostgreSQL deployment on VENOM, Phase 9 must resume at the real
physical gate using safe synthetic targets. It must not infer physical PASS
from repository tests.

## Evidence and rollback

Sanitized machine-readable evidence is
`docs/phase_reports/evidence/PHASE_09_WINDOWS_SATELLITE.json`, validated by
`scripts/phase_09/validate_evidence.py`. Final exact-head CI is represented
only as `EXTERNAL_GITHUB_CHECK_REQUIRED` and will be reported externally.

Rollback removes/stops only the fixed current-user BMO task, optionally revokes
only the Phase 9 satellite device, preserves Core audit history, reverts normal
Git commits, and downgrades migration `20260820_0006` only after active work is
reconciled. It does not remove unrelated processes, applications, or files.

Phase 10 = `NOT_STARTED`.
