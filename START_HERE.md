# Start Here

## Current verified state

- Phase 4 is closed and merged.
- Phase 5A is closed and merged.
- ADR-0007 is accepted and merged through PR #10.
- Current main architecture: Lenovo G450 temporary lightweight control plane
  plus ASUS TUF heavy AI and Windows compute plane.
- The desktop PC is a future migration or upgrade candidate only.
- The Phase 1 VENOM physical safety gate's measured state remains waiting on
  its real-time stability windows on
  `phase-01/venom-physical-safety-gate`.
- Sanitized live evidence records the verified identity, Ethernet path, bounded
  thermal and memory results, dedicated key login, owner visual checks,
  privileged hardening, encrypted backup/restore, reboot recovery, and the
  FINAL official marker `2026-08-19T00:11:05Z` UTC. The preliminary marker and
  both prior official markers (`2026-08-18T22:28:46Z` and
  `2026-08-18T23:29:53Z`) remain historical evidence.
- Immediate closeout passed. Persistent encrypted backup, effective always-on
  lid policy, SMART sector counters, and the real-time evaluator are recorded.
  The real 24-hour gate is active, followed by the real 7-day gate; neither is
  a stability PASS.
- ADR-0008 records an OWNER WAIVER of the unelapsed stability windows as
  blocking prerequisites for Phase 5B progression only. Phase 1 progression is
  `ACCEPTED_WITH_OWNER_WAIVER`; the windows remain
  `WAITING / WAIVED_AS_BLOCKING_PREREQUISITE / still monitoring`.
- Phase 5B runtime behavior passed on draft PR #15, but independent review
  opened a bounded SSH direction-policy and evidence-validator recovery. PR
  #15 is not merge-ready until live negative-forwarding proofs pass. Phase 6
  is unauthorized.

## Before any task

1. Read `AGENTS.md`.
2. Read `docs/IMPLEMENTATION_STATUS.md`.
3. Read the relevant sections of `docs/MASTER_PLAN.md`.
4. Read relevant accepted or superseding ADRs under `docs/adr/`.
5. Read the active task specification completely, inspect the repository and
   tests, then work only within its approved scope.

Codex is the default implementation specialist. Independent review is
read-only and required before Mahmoud, the sole merge and architecture approval
authority, may accept a pull request.

Do not reinstall Ubuntu, broaden VENOM/TUF network exposure, merge PR #15,
start Phase 6, change models, or perform a database migration unless a later
owner-approved task explicitly authorizes it.
