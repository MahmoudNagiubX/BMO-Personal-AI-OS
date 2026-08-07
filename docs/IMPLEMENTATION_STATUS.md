# Implementation Status

> This file records verified repository state and owner-approved architecture. Physical desktop-server state is recorded as verified only when owner-collected execution evidence exists.

- **Plan baseline:** 1.1 — 2026-08-07
- **Current phase:** Phase 5A — software-only model gateway
- **Current state:** PR #8 is merged and Phase 4 is closed. Phase 5A technical implementation and local acceptance are complete on `phase-05a/model-gateway`; the branch remains subject to independent review, final-head GitHub CI, and owner merge.
- **Current branch target:** `phase-05a/model-gateway`
- **Next action:** Independent review, final-head CI verification, and owner merge decision for the Phase 5A PR.
- **Later phases authorized:** Physical deployment is paused. After Phase 5A owner merge, the Desktop Home Server Safety Gate is mandatory before Phase 5B or Phase 6.

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

- PR #7 merged into `main` at `caeb366af121ed3f2dca5239f34346a13f8a031a`.
- PR #8 merged into `main` at `a4a4cf78890c5efe98830a6ecc22757cf9f826f2`.
- Phase 4 technical acceptance is complete and closed on merged `main`.
- Phase 5A implements the software-only model gateway on `phase-05a/model-gateway` with typed local contracts, deterministic routing, bounded resilience, and no cloud fallback.
- The accepted active stack is Qwen3.5 4B plus BGE-M3 only. Qwen3.5 9B is deferred and is not a Phase 4 requirement.
- Phase 5A is the current phase and remains unmerged pending independent review and owner approval.
- After Phase 5A owner merge, coding must stop for the Desktop Home Server Safety Gate.
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
- Xubuntu 24.04 LTS installation and hardening.
- Docker reliability and log rotation.
- Backup and restore.
- 24-hour and seven-day stability.

## Phase boundary

Phase 5A is limited to software-only local model-gateway contracts for the accepted Qwen3.5 4B and BGE-M3 stack. It adds no production deployment, database schema change, tool execution, cloud fallback, memory/RAG, voice, satellite, or Qwen3.5 9B work. Phase 5B and physical deployment have not started. After independent review and owner merge, the next mandatory step is the Desktop Home Server Safety Gate.
