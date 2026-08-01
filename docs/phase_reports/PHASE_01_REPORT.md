# Phase 1 Report - Lenovo Base Hub and Edge Infrastructure

This is a live Phase 1 report, not a completed acceptance report.

## Identity

- **Date:** 2026-08-01
- **Repository:** `MahmoudNagiubX/BMO-Personal-AI-OS`
- **Branch:** `phase-01/lenovo-foundation`
- **Base commit (`main`):** `6137598607f712fd97ba8f04a9c4519ff15f385c`
- **Control-plane target:** Lenovo G450 (hardware identity not yet collected)
- **Development environment:** ASUS TUF / Windows workstation; not a Lenovo execution target

## Preparation completed

- Phase 0 was merged into `main`.
- The Phase 1 branch exists.
- Lenovo preparation files were created and corrected in this macro step.
- Repository-level static validation for the corrected preparation passed.
- No Ubuntu installation or physical Lenovo configuration has occurred.

## Target architecture

These are targets from the accepted plan, not verified Lenovo evidence:

- Lenovo: always-on control plane and home edge hub.
- ASUS TUF: heavy AI compute plane.
- Target OS: Ubuntu Server 24.04 LTS, 64-bit, headless.
- Target hostname: `bmo-control`.
- Target timezone: `Africa/Cairo`.
- Target baseline: SSH public-key access, root login disallowed, UFW allowing OpenSSH, and Docker Engine/Compose from the official signed apt repository.

## Unverified hardware assumptions

No hardware property below has been collected as acceptance evidence: Lenovo model label or BIOS identity; exact CPU model and 64-bit capability; RAM amount and type; disk type, size, and SMART health; battery condition; charger condition; cooling-fan condition; physical Ethernet reliability; and the ability to remain powered on for at least 30 minutes without an unexpected shutdown.

## Physical safety gate: pending

The owner must confirm preservation of needed data, authorize complete internal-disk erasure, and inspect the battery, charger, fan, Ethernet port, installation media, ASUS USB-creation availability, model identity, currently booting OS, sustained power, keyboard, display, and direct physical access.

## Prepared automation

`infrastructure/lenovo-server/bootstrap.sh` now provides:

- `--preflight`: read-only checks for Ubuntu, x86_64/amd64, systemd, privilege requirements, official package-source DNS/HTTPS, disk space, SSH, UFW, Docker, swap, and expected tools.
- `--apply`: fail-closed platform checks plus exact `BMO_LENOVO_BOOTSTRAP_CONFIRM=YES` confirmation.
- Candidate validation and change-only timestamped backups for the managed SSH drop-in, Docker apt source, and Docker daemon configuration.
- SSH syntax validation before a safe service transition, with no automatic password-authentication disablement.
- OpenSSH-only UFW preparation and official signed Docker apt setup with bounded JSON log rotation.
- No disk commands, reboot, shutdown, secret generation, public Docker TCP binding, or remote installer pipeline.

## Not yet executed

- `bootstrap.sh` has not been run with `--preflight` or `--apply` on the Lenovo.
- It has not been run on the ASUS TUF, Windows, WSL, a VM, or any other machine.
- Ubuntu has not been installed by this task.
- No SSH, UFW, Docker, swap, temperature, SMART, reboot, or systemd health result is available.

## Repository validation evidence

- `bash -n infrastructure/lenovo-server/bootstrap.sh` passed using the installed Git Bash parser; the Lenovo script was not executed.
- `uv lock --check`, `uv sync --group dev --locked`, Ruff lint/format, Mypy, all 8 Pytest tests, governance validation, `scripts/check.py`, pre-commit, and `git diff --check` passed.
- The validation ran on the ASUS TUF Windows development workstation and proves repository safety properties only, not Lenovo hardware or service state.

## Acceptance evidence required

After owner authorization and physical installation, collect actual evidence for: Ubuntu version and firmware mode; exact CPU, RAM, and disk inventory; disk SMART health; battery/charger/fan safety; Ethernet reliability; hostname and timezone; SSH key login in a second session; root-login and password-authentication policy; UFW rules and exposed ports; Docker and Compose versions; Docker service state; swap; temperatures; clean reboot; `systemctl --failed`; and 24-hour then seven-day stability.

## Current blockers

- The physical Lenovo safety gate is unanswered.
- Disk erasure is not authorized by this report.
- No owner-approved Ubuntu installation window or installation media evidence exists.
- Later phases are not authorized.

## Next owner action

Answer the 12 physical Lenovo gate questions in the correction handoff. Send the 12 owner answers and this report to ChatGPT. Do not install Ubuntu or run `bootstrap.sh` yet.
