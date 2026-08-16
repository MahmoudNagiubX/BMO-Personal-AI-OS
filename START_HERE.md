# Start Here

## Current verified state

- Phase 4 is closed and merged.
- Phase 5A is closed and merged.
- ADR-0007 is accepted and merged through PR #10.
- Repository cleanup PR #11 is merged at `09593cc1874d997fb4888db326068112cf0afd7f`; the cleanup gate is closed.
- Plan v1.3 / ADR-0008 accept the future typed observation, provenance, World State, and Advanced Context architecture as documentation only.
- Eleven accepted advanced capability families are mandatory long-term BMO implementation targets, but none is implemented or authorized by this architecture update.
- Robotics/physical agents are explicitly out of scope by owner decision dated 2026-08-16; there is no planned robot implementation or simulation phase.
- Current main architecture remains the Lenovo G450 temporary lightweight control plane plus ASUS TUF heavy AI and Windows compute plane.
- The desktop PC is a future migration or upgrade candidate only.
- The next mandatory physical step is the Lenovo G450 Safety Gate and Ubuntu Server 24.04.4 LTS AMD64 Foundation.
- Phase 5B is blocked until that gate passes. Phase 6 is unauthorized.

## Before any task

1. Read `AGENTS.md`.
2. Read `docs/IMPLEMENTATION_STATUS.md`.
3. Read the relevant sections of `docs/MASTER_PLAN.md`.
4. Read relevant accepted or superseding ADRs under `docs/adr/`, including ADR-0008 when context/evidence/future advanced systems are involved.
5. Read the active task specification completely, inspect the repository and tests, then work only within its approved scope.

Codex is the default implementation specialist. Independent review is read-only and required before Mahmoud, the sole merge and architecture approval authority, may accept a pull request.

Do not install Ubuntu, modify the Lenovo, deploy BMO, start Phase 5B or Phase 6, create future World State/context services, add proposal-suggested dependencies, change models, or perform a database migration unless a later owner-approved task explicitly authorizes it. Do not introduce robotics/physical-agent scope unless Mahmoud explicitly reverses that out-of-scope decision through a future ADR.