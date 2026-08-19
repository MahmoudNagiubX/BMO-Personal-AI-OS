# ADR-0008 — Owner waiver of Lenovo stability gates for Phase 5B progression

- **Status:** Accepted
- **Date:** 2026-08-19
- **Deciders:** Mahmoud
- **Supersedes:** None
- **Superseded by:** None

## Context

The current Lenovo G450/VENOM physical-gate evidence has completed its immediate
closeout: Ethernet, bounded thermal and memory checks, storage and LVM
inspection, SMART health and sector counters, SSH and firewall hardening,
bounded journald, encrypted persistent off-device backup and restore proof,
controlled reboot recovery, durable root monitoring, AC-only/no-battery
disposition, and always-on lid policy. The final non-backdated official
stability marker is `2026-08-19T00:11:05Z`; the preliminary marker and both
earlier official markers remain preserved historical evidence.

The real 24-hour and seven-day observation windows have not elapsed. Their
measured states remain `WAITING`; the physical-gate evidence remains
`WAITING_FOR_24H`. The owner has explicitly chosen to waive those unelapsed
windows only as blocking prerequisites for starting Phase 5B.

## Decision

The owner accepts the residual operational risk of beginning Phase 5B before
the 24-hour and seven-day stability observation windows have elapsed. This is
an **OWNER WAIVER** of the windows as blocking progression prerequisites only;
it is not a stability PASS.

The distinct statuses are:

- **Phase 1 progression:** `ACCEPTED_WITH_OWNER_WAIVER`.
- **Phase 5B:** `AUTHORIZED_TO_START` and `NOT YET IMPLEMENTED`.
- **24-hour stability:** `WAITING / WAIVED_AS_BLOCKING_PREREQUISITE`.
- **Seven-day stability:** `WAITING / WAIVED_AS_BLOCKING_PREREQUISITE`.

The root `venom-phase1-stability.timer` remains active. Existing timestamps,
samples, and measured gate fields remain unchanged, and the official clock is
not reset. The waiver does not authorize Phase 5B implementation on PR #14.

## Rationale

Immediate safety, recovery, and monitoring controls have been demonstrated, so
the owner may begin the separately bounded Phase 5B acceptance work after this
PR is independently reviewed and owner-merged. Keeping the live stability
observation in place preserves operational evidence rather than replacing it
with a manually asserted success state.

## Consequences

### Positive

- Phase 5B progression is authorized without misrepresenting unelapsed
  monitoring as a passed stability gate.
- Background monitoring continues to provide real operational evidence.
- The ASUS TUF to GitHub to Lenovo SSH review/deployment workflow is preserved.

### Negative / trade-offs

- There is less long-duration confidence than a completed 24-hour and seven-day
  observation would provide.
- The battery-less host has no ride-through during AC loss; its bounded
  power-disposition evidence is not a power-loss PASS.
- Phase 5B must remain bounded and reversible while monitoring is incomplete.

Material SMART failure, any non-zero SMART sector counters 5/197/198,
repeated thermal breach, root-filesystem pressure, an unexpected reboot
pattern, repeated failed units, or repeated loss of the Ethernet management
path requires pausing deployment expansion and reporting the degradation.

## Security and privacy impact

No service is exposed publicly and no secret, backup plaintext, raw SMART
output, or personal telemetry is added to Git. The waiver does not weaken
private-LAN, SSH, UFW, authentication, backup, or monitoring controls.

## Migration and rollback

This decision affects only Phase 5B progression for the current temporary
Lenovo control plane. Future replacement or migration hosts require their own
24-hour and seven-day safety gates unless the owner records a separate waiver.

Rollback is a normal revert of this governance decision before Phase 5B work
begins. If an operational alert occurs during Phase 5B, pause expansion and
reassess the host rather than treating this waiver as a stability pass.

## Validation

- The physical-gate validator continues to require measured `WAITING` states
  and rejects a claimed PASS while the real windows remain unelapsed.
- Governance tests require this ADR and the explicit owner-waiver wording in
  the canonical status records.
- The root stability timer is verified read-only as enabled and active; no
  thermal, memory, SMART extended, or reboot stress is repeated.
