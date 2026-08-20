# Phase 9 — Windows satellite

## Status

Owner-authorized for implementation on `phase-09/windows-satellite` from exact parent
`24297a9c8ce8ce8d386874949aa3d87e0881d9cc`. Phase 9 is not complete until the
repository checks, exact-head CI, and every physically available acceptance gate have factual
evidence. Phase 10 is `NOT_STARTED`.

## Goal and boundary

Phase 9 adds the first product-owned Windows execution satellite on the ASUS TUF. VENOM remains
the identity, permission, approval, budget, idempotency, and audit authority. The TUF agent only
reports its locally approved capabilities and executes fixed typed operations from an
owner-managed local allowlist.

Allowed operations are bounded telemetry, metadata-only search under approved roots, opening an
approved application or project, volume get/set with measured readback, and starting an approved
workflow by stable ID. Every success has a deterministic verification fact. Owned in-flight work
supports bounded cancellation.

The phase does not add arbitrary shell or PowerShell, arbitrary executables or arguments, PID
killing, arbitrary filesystem access, file contents, browser or coordinate automation, screen or
clipboard capture, microphone/camera/voice, memory/RAG, Home Assistant/MQTT execution, Android,
public listeners, or administrative requirements for normal operation.

## Architecture and authority

```text
authenticated owner client
  -> VENOM Core Phase 8 tool request / approval / audit
  -> static descriptor and executor router
  -> authenticated outbound-established satellite WebSocket
  -> ASUS TUF per-user Windows agent
  -> local allowlist, fixed executor, verification, cancellation
  -> typed observation returned to VENOM
```

The model can propose only typed tool data. It cannot select risk, approval, executor, sandbox,
deadline, verification, process, path, command, or allowlist state. `ToolPlatformService` remains
the only authority that consumes an approval and creates an execution envelope. The descriptor,
not the request, selects the Windows satellite executor.

## Protocol and transport

The protocol identifier is `phase-09-windows-satellite/v1`. The TUF opens an authenticated
WebSocket to `WS /api/v1/satellites/windows/connect`; VENOM never opens an inbound TUF command
connection. Bearer credentials are sent only in the Authorization header. Production requires
`wss://`; plaintext `ws://` is accepted only for loopback tests. Credentials are forbidden in
URLs, query strings, frames, and logs.

All frames are strict Pydantic messages and are capped at 16 KiB. The handshake binds the current
Phase 6 principal, exact `satellite.connect` scope, protocol version, device kind/platform,
software version, and a subset of approved capabilities. Duplicate owner satellite sessions,
wrong versions, malformed/oversized frames, stale session IDs, revoked credentials/devices,
disabled owners, and capability escalation fail closed.

Execution envelopes contain only a generated command/tool-call ID, correlation ID, tool
name/version, validated arguments, canonical argument digest, deadline, and required capability.
The satellite returns a matching typed observation. Heartbeats, bounded identity revalidation,
and capped reconnect backoff detect revocation and offline state.

## Identity, scopes, and capabilities

Phase 6, Phase 7, and Phase 8 scope vocabularies remain unchanged. Phase 9 adds exactly one
transport scope: `satellite.connect`. It grants no tool-request or owner-action authority.

Approved capability IDs are:

- `windows.telemetry.read`
- `windows.files.search`
- `windows.app.open`
- `windows.project.open`
- `windows.media.control`
- `windows.workflow.start`

Capabilities remain separate from scopes. A stolen satellite credential can connect only as its
revocable device and cannot request or approve owner actions.

## Static tool catalog

The Phase 8 synthetic descriptors remain. Phase 9 adds these version-1 descriptors:

| Tool | Risk | Approval | Local capability |
|---|---|---|---|
| `windows.status.read` | read | none | `windows.telemetry.read` |
| `windows.files.search` | read | none | `windows.files.search` |
| `windows.app.open` | reversible | none | `windows.app.open` |
| `windows.project.open` | reversible | none | `windows.project.open` |
| `windows.media.volume.get` | read | none | `windows.media.control` |
| `windows.media.volume.set` | reversible | none | `windows.media.control` |
| `windows.workflow.start` | consequential | exact owner | `windows.workflow.start` |

Inputs expose only stable IDs, a bounded metadata query/result count, or a volume integer from 0
through 100. There is no schema field for a path, executable, argument list, PowerShell text, PID,
risk, approval, executor, or sandbox.

## Local allowlist contract

The untracked owner configuration is strict versioned JSON in the current Windows user's BMO
application-data directory. The repository commits only a safe synthetic template. It maps stable
IDs to canonical absolute local targets:

- apps: exact executable plus fixed argument array and optional fixed working directory;
- projects: exact executable, exact approved project directory, and fixed argument array;
- search roots: exact approved directory;
- workflows: exact executable/interpreter, exact script, fixed arguments, working directory,
  timeout, expected exit codes, cancellation policy, and fixed verification rule.

Duplicate keys or IDs, relative paths, missing required fields, unsupported script/interpreter
combinations, and mutable request-supplied command data are rejected. Missing targets degrade only
their associated local capability. Config cannot be mutated over the network. Execution always
uses argument arrays with `shell=False`.

Metadata search never reads file contents. It remains under the canonical root, rejects traversal,
symlinks, junctions, and reparse points, and enforces entry, result, and deadline bounds.

## Execution, verification, replay, and cancellation

Telemetry returns fresh finite bounded scalar CPU, memory, disk, network, optional battery, and
optional NVIDIA GPU measurements without process lists, environment data, or identifiers. GPU
queries use only a fixed discovered local `nvidia-smi` path.

App and project operations verify the exact configured dispatch and only report observations that
are actually measurable; they never claim that a GUI rendered. Volume set reads back the endpoint
level within a fixed tolerance. Workflow success requires process start, an expected exit code,
and its configured non-secret verification rule.

The satellite binds command ID, tool/version, and argument digest. Same-ID/same-digest delivery
replays a safe cached result; same-ID/different-digest delivery is denied. Read-only work may be
recomputed after a process restart. An interrupted consequential workflow is recorded as uncertain
and is never automatically retried.

Cancellation accepts only a command ID already owned by the satellite instance. It signals only
the corresponding child process, performs a bounded graceful stop, uses a bounded hard stop only
when that workflow explicitly permits it, verifies termination, and returns a typed result. It
never accepts an arbitrary PID or terminates unrelated processes.

## Credential storage and lifecycle

The initial one-time enrollment code is entered only into a bounded local helper and is discarded
after redemption. The returned reusable credential is stored through Windows Credential Manager
under the current user. It is never written as plaintext to Git, config, arguments, environment,
stdout, or logs. Rotation replaces the secure-store value only after server success. Cleanup
deletes only the BMO-owned credential target.

The satellite runs as one limited per-user background agent in the interactive Windows session.
A limited per-user Scheduled Task at logon is the accepted lifecycle; Session 0 and normal-use
elevation are forbidden. Logs are structured, redacted, rotating, and bounded. Reconnect uses
capped exponential backoff with jitter.

## Privacy and security

No credentials, enrollment codes, full environment, cookies, file contents, raw personal search
results, model output, or broad command lines are logged or committed. Evidence contains only
sanitized scalar outcomes and synthetic IDs. There is no continuous screen, audio, location, or
browser monitoring and no inbound TUF listener.

Satellite offline state disables only Windows tools and never makes the Core API, Ollama, BGE-M3,
or the optional advanced provider appear dead. There is no fallback to shell, browser, cloud, or
another device.

## Deployment and rollback

Physical enrollment requires an already deployed Phase 6–8 Core API and PostgreSQL authority on
VENOM plus an authenticated private/TLS WebSocket endpoint. Missing historical production
prerequisites are reported rather than silently deployed by Phase 9.

Deployment installs the exact reviewed commit, creates the untracked local allowlist, redeems one
short-lived enrollment, stores the credential in Windows Credential Manager, runs the agent as the
normal user, and optionally installs the limited at-logon task. No firewall rule or inbound listener
is created.

Rollback removes the BMO per-user startup task, stops only the BMO satellite instance, and retains
audit history. Credential deletion/revocation occurs only for intentional decommissioning. Code
rollback is a normal Git revert. If the Phase 9 migration is applied, its normal Alembic downgrade
restores the previous Phase 8.5 schema after an approved backup gate where real data exists.

## Testing and evidence

Unit, contract, API, security, concurrency, and PostgreSQL tests cover authentication/scope/
revocation, protocol/frame/version validation, reconnect and duplicate sessions, digest/deadline/
replay behavior, immutable descriptor policy, offline state, strict allowlists and path containment,
fixed arguments and `shell=False`, typed execution/verification, workflow timeout/cancellation,
error sanitization, approval expiry/replay, and preserved Phase 8 authority.

Physical evidence, when prerequisites permit, proves normal-user startup, outbound connection,
identity/capabilities/heartbeat, every accepted tool, exact approval, cancellation, duplicate and
offline behavior, revocation, audit/redaction, no listener, volume restoration, harmless workflow
cleanup, idle CPU/RAM, latency, and zero crashes. Machine-readable evidence has a strict validator
and never self-attests final exact-head CI.

## Acceptance criteria

Phase 9 is complete only when VENOM authorizes and audits a strict typed request, sends it over the
authenticated outbound-established channel to the enrolled TUF satellite, the satellite executes
only a local allowlisted operation in the user session, verifies the result, supports bounded
cancellation/replay protection, and reports honest offline state while arbitrary shell, arbitrary
paths, policy selection, credential leakage, inbound/public listeners, and Phase 10 remain
impossible.

Phase 10 = `NOT_STARTED`.
