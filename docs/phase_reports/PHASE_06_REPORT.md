# Phase 6 Completion Report

## Outcome

Phase 6 owner identity, device enrollment, transport authentication, heartbeat, capability
inventory, credential rotation, and device revocation are implemented on draft PR #16. Phase 5B
behavior and evidence are unchanged. Phase 7 was not started.

## Implementation

- Owner bootstrap is local CLI-only, creates the first owner only under an application check plus
  database singleton constraint, and has no reusable admin password or unauthenticated HTTP
  mutation surface.
- Local enrollment fixes the approved owner, device metadata, four-scope vocabulary, capability
  allowlist, and one-to-thirty-minute TTL before the device receives a code.
- The 192-bit URL-safe code is hash-only at rest. PostgreSQL `SELECT ... FOR UPDATE` consumption
  creates exactly one device and one initial live credential under one transaction.
- Opaque credentials contain an indexed public ID and a 256-bit secret. Only the SHA-256 secret
  hash persists and `hmac.compare_digest` verifies it.
- Generic 401 and typed 403 behavior, sanitized self metadata, bounded heartbeat, current approved
  capability subset, atomic rotation, and soft revocation are implemented at product-owned service
  boundaries rather than in routes. Rotation and revocation share device-first lock ordering.
- Alembic revision `20260819_0002` provides normalized associations, ownership constraints,
  bounded status/data constraints, unique hashes/public IDs, indexes, and deterministic downgrade.

## Validation

Before the implementation commit, Ruff lint/format, strict mypy, governance/secret guard,
pre-commit, and `git diff --check` passed. After independent-review hardening, the complete local
non-integration suite passed with 318 tests and six PostgreSQL integration tests deselected because
local Docker was unavailable.
GitHub CI run 100 passed on exact implementation commit
`8d0aeb2852080badb1a16eec3b18b2f516b7ea32`. It is the authoritative PostgreSQL path and covers
migration upgrade/current/check, downgrade/re-upgrade, pgvector/readiness, and independent-session
concurrent enrollment. The final evidence/documentation head requires its own exact-head CI.

The Phase 6 suite adds 47 unit/API/evidence/security tests plus three PostgreSQL lifecycle
concurrency tests: enrollment single-use, owner singleton bootstrap, and rotation/revocation race.
It covers every required negative auth/enrollment/scope/capability/rotation/revocation and secret
leak boundary. The evidence validator has rejection regressions for unsafe, boolean-only, pending
CI, or sensitive claims.

Independent read-only review initially found concurrent-owner, inverse lock-order, database-error
parameter, and pending-CI evidence blockers. Normal security commit
`45cfdd853f779e98f1e55274ab24dc94cb963118` corrects all four without weakening the Phase 6 or
Phase 5B boundaries. Authoritative GitHub CI run 101 passed on that exact security commit, including
all six PostgreSQL integration tests and the deterministic migration cycle. A second independent
read-only review verified each repair and reported no remaining merge-blocking finding.

## Deployment and operational status

No Phase 6 component was persistently deployed to VENOM. The repository and CI acceptance does not
require a physical Core API/PostgreSQL deployment, so the 4 GB host database resource-admission
gate was not invoked. There was no sudo checkpoint, host mutation, real owner/device data, or data
migration risk.

The latest accepted Phase 1 sample remains the sanitized `2026-08-19T07:31:29Z` record: 38°C, 9%
root usage, zero failed units, SMART passed, and counters 5/197/198 at zero. Monitoring remains
active under ADR-0008. The merged Phase 5B exact security/model baseline is preserved; no physical
change required a new model-gateway health test.

## Security and data impact

No raw enrollment code, raw credential, Authorization header, credential/code hash, database URL,
private material, owner personal data, prompt/model content, or telemetry is committed. Synthetic
fixtures use non-personal labels. Heartbeat stores one bounded current state rather than telemetry
history. SQL parameters are hidden from rendered exceptions, and generic request-validation errors
do not echo rejected values. Existing health/version exposure is unchanged and no public/LAN
listener or firewall rule was added.

## Rollback

Repository rollback uses a normal revert. The Phase 6 schema downgrade returns to revision
`20260803_0001` and affects only Phase 6 tables. If real identity data later exists, first stop the
API, create and verify an encrypted off-device database backup, and obtain explicit owner approval;
never silently destroy owner/device history. Phase 1 monitoring, Phase 5B tunnel/probe, and model
files are preserved.

Sanitized evidence: `infrastructure/home_server/evidence/phase_06_identity_enrollment.json`.
