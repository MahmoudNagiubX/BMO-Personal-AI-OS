# Implementation Status

> This file records verified repository state and owner-approved architecture. Physical desktop-server state is recorded as verified only when owner-collected execution evidence exists.

- **Plan baseline:** 1.1 — 2026-08-07
- **Current phase:** Phase 4 — TUF model node, with a blocking architecture-governance update in review
- **Current state:** Phase 3 and the Phase 4 sequencing authorization are merged. Phase 4 implementation has not started. ADR-0005 replaces the Lenovo with the desktop home server as the always-on control plane.
- **Current branch target:** `phase-04/desktop-server-control-plane`
- **Next action:** Independent review, CI verification, and owner merge decision for the desktop-server architecture update.
- **Later phases authorized:** After this architecture update is merged, Phase 4 TUF model-node implementation remains authorized. Phase 5A software-only model-gateway work may follow Phase 4 acceptance. Physical deployment then pauses for the Desktop Home Server Safety Gate before Phase 5B and Phase 6.

## Accepted topology

### Desktop home server — always-on control plane

ADR-0005 is the active host decision. Owner-reported hardware baseline:

- AMD Ryzen 5 3600, 6 cores / 12 threads.
- Gigabyte B550 AORUS ELITE motherboard.
- 8 GB system RAM.
- NVIDIA GeForce GT 710 with 2 GB VRAM.
- 128 GB SSD.
- Approximately 350 GB HDD.
- Cooler Master 600 W power supply.

Planned operating baseline:

- Xubuntu 24.04 LTS, 64-bit, with XFCE available for troubleshooting, local management, and recovery. Core services do not depend on a GUI login.
- Docker Compose.
- Wired Ethernet.
- Hostname `bmo-control` unless changed by a later ADR.
- No overclock or PBO.
- Sustained normal-load CPU temperature target below 75 °C.
- SMART monitoring, bounded logs, power-loss recovery, off-device backups, and restore testing.
- 24-hour then seven-day stability gates before production acceptance.

The GT 710 is retained for display and recovery only. It is not an AI inference device. The current 8 GB RAM and 128 GB SSD are accepted for the initial lightweight baseline, with 16 GB RAM, a 500 GB or larger SSD, and a UPS recorded as the first recommended upgrades.

### ASUS TUF — heavy compute and Windows execution plane

The ASUS TUF remains responsible for Ollama, Qwen3.5 4B as the initial primary generation/orchestration/vision model, BGE-M3 embeddings, heavy speech/vision/indexing, the Windows satellite, isolated browser automation, development, and benchmarks. Qwen3.5 9B is deferred, not an active required model, and not a Phase 4 blocker; Codex remains the coding specialist.

## Lenovo retirement

- ADR-0003 is superseded by ADR-0005.
- The Lenovo G450 is removed from active architecture, deployment, sequencing, and acceptance gates.
- `phase-01/lenovo-foundation` remains unmerged and is retired.
- The retired branch and historical reports are preserved only as audit history until the owner explicitly requests deletion.
- No future Lenovo installation or deployment is authorized by historical documentation.
- Future physical-server foundation work must start from then-current `main` on `phase-01/home-server-foundation`.

## Verified sequencing state

- Current merged `main` baseline before this branch: `e87efae9032b521a938ad1ae03f942a81ffb9e40` (PR #6 merge).
- Phase 4 remains authorized on the ASUS TUF but has not started.
- Phase 5A software-only model-gateway work remains authorized only after Phase 4 acceptance.
- After Phase 5A, coding must stop for the Desktop Home Server Safety Gate.
- Phase 5B deployment acceptance and Phase 6 remain unauthorized until the desktop-server gate passes.
- The accepted sequence is **architecture update → Phase 4 → Phase 5A → Desktop Home Server Safety Gate → Phase 5B → Phase 6**.

## Verified Phase 2 implementation state

- The health-only FastAPI application factory, typed settings, structured logging, correlation IDs, SQLAlchemy foundation, Alembic baseline, and PostgreSQL/pgvector Compose and CI definitions are merged.
- PR #4 completed the bounded Phase 2 foundation.
- GitHub Actions verified Python 3.12, PostgreSQL/pgvector, migration revision `20260803_0001`, and the real vector-extension integration path.
- Local Docker integration was unavailable on the development machine; GitHub CI is the authoritative PostgreSQL result for that closeout.

## Verified Phase 3 implementation state

- OpenJarvis is pinned as the official `OpenJarvis==1.0.0` PyPI artifact while retaining provenance to release tag `v1.0.0` and commit `e97088f199cf86ea5f78de921772357d1f0d2cec`.
- Direct OpenJarvis imports remain confined to the adapter boundary.
- Local-only request flow, bounded identifiers, trace redaction, contract behavior, and PostgreSQL integration passed accepted CI.
- PR #5 is merged into `main`.
- Phase 3 added no model download, cloud fallback, analytics traffic, tool execution, production endpoint, or physical-server deployment.

## Physical desktop-server evidence still required

The hardware specifications above are owner-reported and accepted for planning. Production acceptance still requires direct evidence for:

- Exact motherboard revision, BIOS version, RAM layout, disk models, and power-supply model/condition.
- SSD and HDD SMART health.
- Memory stability.
- CPU and system temperatures under load.
- Fan operation and dust condition.
- Ethernet stability.
- AC power-return behavior.
- Ubuntu Server installation and hardening.
- Docker reliability and log rotation.
- Backup and restore.
- 24-hour and seven-day stability.

## Phase boundary

This branch changes architecture and governance only. It does not install Ubuntu, alter physical hardware, deploy containers, download models, change the database schema, or begin Phase 4 implementation. Phase 4 product work remains blocked until this architecture PR is independently reviewed, green in CI, and merged by the owner.
