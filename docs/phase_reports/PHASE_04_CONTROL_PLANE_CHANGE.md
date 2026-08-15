# Phase 4 Governance — Desktop Control-Plane Change Report

## Result

> Historical record: this report records the ADR-0005 desktop-host decision as it stood in 2026-08. ADR-0007 supersedes that decision; the desktop is now a future upgrade candidate and the Lenovo G450 is the temporary active control plane. The historical report is preserved without rewriting its contemporaneous evidence.

Architecture change implemented on `phase-04/desktop-server-control-plane`; its independent review and GitHub CI completed before the later ADR-0007 supersession.

## Owner decision

The Lenovo G450 is removed from the active BMO architecture. The owner selected the existing desktop PC as the always-on control plane while retaining the ASUS TUF as the heavy AI compute and Windows execution node.

## Owner-reported desktop hardware

- AMD Ryzen 5 3600, 6 cores / 12 threads.
- Gigabyte B550 AORUS ELITE motherboard.
- 8 GB system RAM.
- NVIDIA GeForce GT 710 with 2 GB VRAM.
- 128 GB SSD.
- Approximately 350 GB HDD.
- Cooler Master 600 W power supply.

These values are accepted for architecture planning but are not yet physical installation evidence.

## Accepted server baseline

- Xubuntu 24.04 LTS, 64-bit, with XFCE available for troubleshooting and recovery; services must not depend on GUI login.
- Docker Compose.
- Wired Ethernet.
- Hostname `bmo-control` unless a later ADR changes it.
- Private-network service bindings.
- Stock CPU operation with no overclock or PBO.
- GT 710 retained only for display, firmware setup, and recovery.

## Control-plane responsibilities

- Core API and orchestration.
- Identity, device registry, permissions, approvals, audit, and scheduler.
- PostgreSQL/pgvector after storage and load gates.
- Home Assistant Container.
- Mosquitto MQTT.
- Model gateway, TUF availability routing, and optional Wake-on-LAN.
- Lightweight retrieval and notifications.
- Encrypted backups and private service discovery.

## ASUS TUF responsibilities

- Ollama and accepted Qwen model builds.
- BGE-M3 where benchmarks justify it.
- Heavy speech, vision, indexing, and model evaluation.
- Windows satellite and isolated browser execution.
- Development and benchmarking.

## Initial model stack

- Qwen3.5 4B is the initial primary model for generation, conversation, orchestration, vision, structured output, and tool-call data.
- BGE-M3 provides embeddings and retrieval support.
- Codex is the coding specialist.
- Qwen3.5 9B was investigated historically but is deferred, not required for MVP or Phase 4 acceptance, and is not automatically restored.

## Two-year preservation policy

A two-year always-on service window is accepted subject to the following controls:

- No overclock or PBO.
- Normal sustained CPU temperature target below 75 °C.
- Fan verification and dust cleaning every 3–6 months.
- SSD/HDD SMART and temperature monitoring.
- Alerts for reallocated, pending, or uncorrectable sectors.
- Docker and application log rotation.
- Wired Ethernet for production.
- Quality surge protector and preferred UPS.
- Automatic recovery after AC power returns.
- Off-device backups and restore drills.
- 24-hour then seven-day stability gates.

## Storage and upgrades

- The 128 GB SSD is the initial OS and service disk after health checks.
- The HDD may contain non-critical archives and one backup copy, never the only critical copy.
- PostgreSQL placement requires SMART, free-space, write-load, backup, and restore evidence.
- First recommended upgrades: at least 16 GB RAM, a 500 GB or larger SSD, and a UPS.
- Exact future CPU compatibility must be checked against the motherboard revision and BIOS before purchase.

## Lenovo retirement and migration

- ADR-0003 is superseded by ADR-0005.
- `phase-01/lenovo-foundation` is retired and must not be merged.
- Historical Lenovo branches and reports remain audit history only until explicit owner deletion authorization.
- Future physical-server work starts from then-current `main` on `phase-01/home-server-foundation`.
- The Lenovo is not automatically reinstated if the desktop server fails acceptance.

## Sequencing

The accepted sequence is:

1. Merge this architecture update.
2. Complete Phase 4 on the ASUS TUF.
3. Complete Phase 5A software-only model-gateway work.
4. Stop for the Desktop Home Server Safety Gate.
5. Complete the replacement Phase 1 home-server foundation.
6. Continue to Phase 5B deployment acceptance.
7. Begin Phase 6 only after the server gate passes.

## Scope boundary

This change is documentation, architecture governance, and governance tests only. It does not install Xubuntu or another operating system, modify physical hardware, deploy containers, download models, alter database schema, or begin Phase 4 product implementation.

## Changed files

- `README.md`
- `AGENTS.md`
- `CONTRIBUTING.md`
- `docs/IMPLEMENTATION_STATUS.md`
- `docs/MASTER_PLAN.md`
- `docs/adr/0001-architecture-baseline.md`
- `docs/adr/0003-compute-control-split.md`
- `docs/adr/0005-desktop-server-control-plane.md`
- `docs/adr/0006-initial-model-stack.md`
- `docs/phase_reports/PHASE_04_CONTROL_PLANE_CHANGE.md`
- `scripts/verify_governance.py`
- `tests/test_repository_governance.py`

## Validation status

- Repository diff is confined to architecture documentation, governance code, and governance tests.
- The branch is based on current `main` and has no merge-base divergence.
- GitHub CI and independent review are pending at the time this report is written.
- No physical or runtime result is claimed.

## Rollback

Revert the architecture PR before physical deployment. Continue software-only work on the ASUS TUF and select another always-on host through a new ADR. Do not silently reactivate the Lenovo plan.
