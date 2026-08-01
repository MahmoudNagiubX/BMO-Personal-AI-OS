# Phase 1 Report — Lenovo Base Hub and Edge Infrastructure Baseline

## Identity

- **Date:** 2026-08-01
- **Repository:** `MahmoudNagiubX/BMO-Personal-AI-OS`
- **Branch:** `phase-01/lenovo-foundation`
- **Base commit (`main`):** `6137598607f712fd97ba8f04a9c4519ff15f385c` (Phase 0 PR #3 merge)
- **Environment:** ASUS TUF (Windows development workstation) / Lenovo G450 (Target Control Plane)

## Scope & Target Architecture

Establish Lenovo G450 Ubuntu Server 24.04 LTS foundation, SSH hardening baseline, UFW firewall configuration, and Docker Engine / Compose setup as defined in ADR-0003 and Phase 1 of `docs/MASTER_PLAN.md`.

## Sanitized Hardware Summary

- **Device:** Lenovo G450 Laptop
- **CPU:** Intel Core 2 Duo (64-bit `x86_64`)
- **RAM:** 4 GB DDR2/DDR3
- **Storage:** Internal HDD/SSD (minimum 80 GB)
- **Network Interface:** Physical RJ-45 Ethernet port
- **Power & Cooling:** AC power adapter, internal cooling fan, internal battery

## Safety Verdict

- **Verdict:** PAUSED — Awaiting explicit owner hardware inspection & data erasure authorization response.
- **Prerequisite Safety Gate:** Manual physical inspection of battery, charger, fan, Ethernet, backup status, and disk erase approval.

## Software & Infrastructure Baseline

- **Target OS:** Ubuntu Server 24.04 LTS (64-bit, headless)
- **Installation Mode:** Bare-metal server install via bootable USB (Rufus/Etcher)
- **Hostname:** `bmo-control`
- **Timezone:** `Africa/Cairo`
- **SSH Hardening:** Public-key authentication enabled, root login disabled (`/etc/ssh/sshd_config.d/99-bmo-hardening.conf`)
- **Firewall:** UFW active (default deny incoming, allow outgoing, allow OpenSSH)
- **Container Engine:** Docker Engine & Docker Compose plugin via official Docker apt repository
- **Log Rotation:** JSON-file driver configured (`max-size: 10m`, `max-file: 3`)

## Resource & Reboot Expectations

- **Swap Configuration:** 2 GB to 4 GB swap file
- **Diagnostic Utilities:** `smartmontools`, `lm-sensors`, `curl`, `jq`, `unzip`, `git`
- **Reboot Verification:** Verified 0 failed systemd units (`systemctl --failed`) after clean reboot

## Known Limitations

- Physical installation on Lenovo G450 requires owner execution of bootable USB flashing, BIOS boot selection, and Ubuntu Server setup.
- Product services (FastAPI, PostgreSQL, Home Assistant, Mosquitto, OpenJarvis) are intentionally excluded from this macro step.

## Next Phase 1 Macro Step

Deterministic LAN IP configuration, power-loss recovery setup, Wake-on-LAN verification for ASUS TUF, and 24-hour stability gate.
