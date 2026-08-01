# Implementation Status

> This file records verified repository state. Physical Lenovo state is recorded only when owner-collected execution evidence exists.

- **Plan baseline:** 1.0 - 2026-07-31
- **Current phase:** Phase 1 - Lenovo Base Hub and Edge Infrastructure
- **Current state:** Lenovo automation preparation exists; no physical Lenovo installation or configuration has occurred; the hardware safety gate is pending.
- **Current branch target:** `phase-01/lenovo-foundation`
- **Next action:** Owner answers the physical safety questions; then Ubuntu installation begins.
- **Later phases authorized:** No

## Verified current Phase 1 facts

- Phase 0 was merged into `main` at `6137598607f712fd97ba8f04a9c4519ff15f385c`.
- The `phase-01/lenovo-foundation` branch exists.
- Lenovo preparation files exist in `infrastructure/lenovo-server/`.
- The preparation files passed repository-level static checks for this correction.
- No physical Lenovo configuration has been performed.
- The physical Lenovo safety gate is pending.

## Target configuration (not physical evidence)

- Ubuntu Server 24.04 LTS, 64-bit, headless.
- Lenovo as the always-on control plane; ASUS TUF remains the heavy compute plane.
- Target hostname `bmo-control` and timezone `Africa/Cairo`.
- SSH public-key baseline, UFW with OpenSSH allowed, Docker Engine and Compose plugin from the official signed apt repository.
- Bounded Docker JSON log rotation and Docker enabled on boot.

## Not verified on the Lenovo

The following require owner inspection or execution evidence: exact CPU model and 64-bit capability; exact RAM amount and type; disk type, size, and SMART health; battery, charger, and cooling-fan condition; Ethernet reliability; installed Ubuntu version; firmware mode; disk erase; hostname; timezone; SSH key authentication; root-login policy; password-authentication status; UFW state and exposed ports; Docker/Compose versions and service state; swap size; temperatures; SMART result; reboot success; and `systemctl --failed` output.

## Phase boundary

This phase currently stops at preparation and the physical hardware safety gate. Do not install Ubuntu or run `bootstrap.sh` until the owner has answered the gate questions and explicitly proceeds. No later phase has started or been authorized.
