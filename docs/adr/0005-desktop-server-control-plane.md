# ADR-0005 — Replace Lenovo with the desktop home server control plane

- **Status:** Accepted
- **Date:** 2026-08-07
- **Deciders:** Mahmoud
- **Supersedes:** ADR-0003
- **Superseded by:** None

## Context

The original architecture assigned the always-on control plane to the Lenovo G450. The owner has now selected an existing desktop PC as the permanent home-server candidate and removed the Lenovo from the active BMO topology.

The owner-reported desktop hardware is:

- AMD Ryzen 5 3600, 6 cores / 12 threads.
- Gigabyte B550 AORUS ELITE motherboard.
- 8 GB system RAM.
- NVIDIA GeForce GT 710 with 2 GB VRAM.
- 128 GB SSD.
- Approximately 350 GB HDD.
- Cooler Master 600 W power supply.

The ASUS TUF remains the Windows workstation and heavy AI compute node. The desktop is materially stronger than the Lenovo for databases, containers, Home Assistant, MQTT, scheduling, and core services while preserving a future upgrade path.

## Decision

Use the desktop PC as the BMO always-on control plane and home edge server. Remove the Lenovo G450 from all active architecture, deployment, sequencing, and acceptance gates.

The desktop server will use:

- Xubuntu 24.04 LTS, 64-bit, with XFCE available for troubleshooting, local management, and recovery. Core services use systemd and Docker Compose and must not depend on a GUI login.
- Docker Compose for infrastructure and selected product services.
- Wired Ethernet as the normal network path.
- Hostname `bmo-control` unless a later ADR changes it.
- Stock CPU operation: no overclock and no PBO for the always-on baseline.

The desktop server owns:

- Core API and orchestration.
- Identity, device registry, permissions, approvals, audit, and scheduler.
- PostgreSQL and pgvector after storage and load gates pass.
- Home Assistant Container.
- Mosquitto MQTT.
- Model gateway, TUF health routing, and optional Wake-on-LAN.
- Lightweight retrieval, notifications, backups, and private service discovery.

The ASUS TUF owns:

- Ollama and accepted Qwen model builds.
- BGE-M3 embeddings when GPU/latency benefit justifies it.
- Heavy speech, vision, indexing, and model evaluation.
- Windows satellite and isolated browser execution.
- Development, benchmarking, and repository tooling.

The GT 710 is retained for display, firmware setup, and recovery access. It is not an AI inference device. The Ryzen 5 3600 has no integrated graphics, so removal of the GT 710 requires a separately verified headless-boot and recovery plan.

## Storage and upgrade policy

Initial placement:

- The 128 GB SSD hosts Ubuntu, Docker, product configuration, and active services after health checks.
- The HDD may hold non-critical archives and one backup copy, but it must never be the only copy of critical data.
- PostgreSQL placement is accepted only after SMART, free-space, write-load, backup, and restore checks.

First recommended upgrades:

1. Increase system RAM from 8 GB to at least 16 GB before sustained operation of the full database, Home Assistant, memory/RAG, and multiple product containers.
2. Replace or supplement the 128 GB SSD with a 500 GB or larger SSD for comfortable logs, database growth, indexes, and updates.
3. Add a UPS when practical; a surge protector alone does not provide graceful shutdown during outages.

The motherboard and platform retain a future CPU/RAM/storage upgrade path. Exact processor support must be checked against the motherboard revision and installed BIOS before any purchase.

## Two-year service and hardware-preservation policy

A two-year always-on service window is accepted. Continuous light-to-moderate server use is not considered harmful by itself; the main wear risks are storage, fans, dust, power quality, and sustained heat.

Required controls:

- Keep CPU settings at stock; no overclock or PBO.
- Target sustained CPU temperatures below 75 °C during normal server load.
- Verify fan operation and clean dust every 3–6 months.
- Monitor SSD/HDD SMART data and temperatures; alert on reallocated, pending, or uncorrectable sectors.
- Enable Docker log rotation and bounded application retention.
- Use Ethernet for the production path.
- Use a quality surge protector and prefer a UPS.
- Configure automatic recovery after AC power returns.
- Keep off-device backups and perform restore drills.
- Run a 24-hour stability gate, then a seven-day stability gate before production acceptance.

## Rationale

This change provides substantially more CPU and memory headroom than the Lenovo, reduces the risk of an underpowered control plane, and allows the Lenovo to be retired without sacrificing local-first operation. It also avoids consuming the ASUS TUF as the always-on authority while keeping the TUF available for GPU-heavy work.

## Consequences

### Positive

- More reliable capacity for PostgreSQL, pgvector, Home Assistant, MQTT, and Docker.
- Better future expansion and repairability.
- The TUF can be turned off while deterministic services continue.
- The Lenovo is no longer a deployment blocker.

### Negative / trade-offs

- Higher electricity use than the Lenovo.
- The current 8 GB RAM and 128 GB SSD impose an initial resource budget.
- Old storage, fans, and power-supply health require monitoring.
- No battery-backed shutdown exists without a UPS.
- Full AI conversation can still degrade when the TUF is offline.

## Security and privacy impact

All services remain local-first, private-network only, authenticated, scoped, and non-public. PostgreSQL, MQTT, Home Assistant, Ollama, and internal APIs must not be exposed directly to the public Internet. The server stores no real secrets in Git and uses encrypted, restore-tested backups.

## Migration

- Retire `phase-01/lenovo-foundation`; it must not be merged into `main`.
- Preserve that remote branch and historical reports only as audit history until the owner explicitly requests deletion.
- Replace the Lenovo Physical Safety Gate with the Desktop Home Server Safety Gate.
- Start future physical-server work from the then-current `main` branch on `phase-01/home-server-foundation`.
- Keep stable service names and interfaces so the host change does not leak into product-domain code.

## Rollback

If the desktop fails its hardware, thermal, storage, power, or stability gates, do not deploy production data. Continue software-only development on the ASUS TUF and select another always-on host through a new ADR. The Lenovo is not automatically reinstated.

## Validation

- Confirm exact hardware inventory and motherboard revision.
- Verify SSD and HDD SMART health.
- Run memory and CPU stability checks.
- Verify thermals, fans, Ethernet, and power-loss recovery.
- Install and harden Xubuntu 24.04 LTS with server-style, GUI-independent services.
- Verify Docker, log rotation, backups, and restore.
- Pass 24-hour and seven-day service stability gates.
