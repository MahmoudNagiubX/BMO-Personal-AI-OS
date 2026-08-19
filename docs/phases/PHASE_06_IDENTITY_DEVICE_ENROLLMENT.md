# Phase 6 — Identity and Device Enrollment

## Status

Implemented on `phase-06/identity-device-enrollment` and awaiting independent review on draft
PR #16. Phase 7 is `NOT_STARTED`.

## Scope

Phase 6 establishes one explicit owner identity, independently revocable devices, short-lived
one-time enrollment, fixed transport scopes, approved/reported capability inventory, opaque device
credentials, bearer authentication, heartbeat, credential rotation, and local device revocation.
It does not add conversation, clients, tools, approvals, voice, memory, home automation, cloud
authentication, or public exposure.

## Security invariants

- The first owner is created only by `scripts/phase_06/bootstrap_owner.py`; a second bootstrap is
  refused, including under concurrency through a database singleton constraint. There is no remote
  owner-administration route and no owner password.
- Enrollment codes contain 192 random bits, default to ten minutes, cannot exceed thirty minutes,
  are returned once, and are stored only as SHA-256 hashes.
- Redemption accepts only a code. A PostgreSQL row lock transaction consumes that enrollment,
  copies only its locally approved identity/scopes/capabilities, creates one device and one initial
  credential, and rejects expiry, replay, and concurrent second redemption.
- Credentials use `public_id.secret`, with a 256-bit random secret. Only the indexed public ID and
  SHA-256 secret hash persist, and verification uses `hmac.compare_digest`.
- Authentication fails with a generic 401 for malformed, unknown, wrong, revoked, disabled-owner,
  or revoked-device identity. Missing scope is 403.
- Device types grant no privilege. The only scopes are `device.self.read`,
  `device.heartbeat.write`, `device.capabilities.report`, and `device.credential.rotate`.
- Capability inventory is normalized and separate from scopes. A heartbeat may report only a
  current subset of the owner's approved capability allowlist.
- Rotation atomically creates a replacement and revokes the credential used for rotation. Device
  revocation soft-revokes the device and all of only its live credentials. Both operations lock the
  device before credentials, preventing an inverse-order deadlock and preserving fail-closed state.
- SQLAlchemy hides all bound parameters in rendered database errors, including credential/code
  hashes. Request-validation errors are generic and never echo rejected enrollment input.

## Interfaces

Local-only administration:

```text
scripts/phase_06/bootstrap_owner.py
scripts/phase_06/create_enrollment.py
scripts/phase_06/list_devices.py
scripts/phase_06/revoke_device.py
```

HTTP boundary:

```text
POST /api/v1/enrollment/redeem
GET  /api/v1/devices/me
POST /api/v1/devices/me/heartbeat
POST /api/v1/devices/me/credentials/rotate
```

Health and version remain public. Enrollment redeem is protected by the one-time code; every other
new route requires an opaque bearer credential and exact scopes.

## Persistence and recovery

Alembic revision `20260819_0002` adds owners, devices, device credentials, device scopes, device
capabilities, enrollments, enrollment scopes, and enrollment capabilities. The downgrade removes
only these Phase 6 tables in dependency-safe order and returns to `20260803_0001`.

Before a destructive downgrade where real identity data exists, stop the API, create and verify an
encrypted off-device PostgreSQL backup, and obtain owner approval. Normal repository rollback is a
new revert commit. No Phase 6 physical deployment occurred on VENOM, so there is no host service to
remove; Phase 1 monitoring and the Phase 5B tunnel/probe remain unchanged.

## Acceptance boundary

GitHub CI is authoritative for migration upgrade/current/check, deterministic downgrade/re-upgrade,
and the two-session PostgreSQL concurrent-redemption test. Sanitized acceptance evidence is in
`infrastructure/home_server/evidence/phase_06_identity_enrollment.json` and is enforced by
`scripts/phase_06/validate_evidence.py`.

Phase 7 remains `NOT_STARTED`.
