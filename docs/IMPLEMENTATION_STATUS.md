# Implementation Status

> This file records verified repository state, owner-approved architecture, and the current sanitized VENOM physical-gate evidence. The Lenovo Safety Gate is not complete.

- **Plan baseline:** 1.3 — 2026-08-18
- **Current phase boundary:** Phase 1 Lenovo/VENOM repository foundation and physical safety gate; current status is IN PROGRESS.
- **Current state:** PR #9 is merged and Phase 5A is closed. PR #10 is merged and PR #13 is merged into `main` at `a02d08a5012938b165e5e26c88708cda9f1bff9e`. The current physical-gate work is on `phase-01/venom-physical-safety-gate`.
- **Current evidence:** Live identity, Ethernet route, thermal peak, bounded memory, dedicated key login, and owner visual safety checks are recorded in `infrastructure/home_server/evidence/venom_physical_gate.json`.
- **Current branch target:** `phase-01/venom-physical-safety-gate` until the physical-gate follow-ups and real stability windows are independently reviewed and owner-merged.
- **Next mandatory physical action:** Complete privileged SSH/UFW/log/backup/recovery work, then allow the real 24-hour and 7-day gates to elapse.
- **Later phases authorized:** Phase 5B is blocked and Phase 6 is unauthorized until the Lenovo G450 Safety Gate passes. No BMO deployment has occurred.

## Accepted topology

### Lenovo G450 — temporary lightweight always-on control plane

ADR-0007 is the active host decision. Owner-provided physical handoff facts are:

- Intel Core 2 Duo T6500, 2 cores, x86_64.
- Approximately 4 GB RAM.
- `/dev/sda`, Seagate ST9320325AS, approximately 298 GB.
- Physical RJ-45 Ethernet.
- No useful AI GPU and no local heavy inference.

The same handoff records Ubuntu Server 24.04.4 LTS, hostname `venom-server`,
Linux user `venom`, OpenSSH reachability, UFW enabled with SSH allowed, clean
SMART evidence, and the manual `~/venom` FastAPI proof-of-life. These facts do
not constitute completion of the physical Safety Gate.

The operating baseline is Ubuntu Server 24.04.4 LTS AMD64, headless, with no desktop GUI. Preserve Legacy BIOS/MBR compatibility in installation planning, but do not claim the exact firmware boot mode before inspection. DHCP is acceptable for initial installation; any fixed address or DHCP reservation follows network inspection. SSH is required after installation. Services remain private-LAN only, with no public port forwarding.

The Lenovo may provide the Core API and lightweight orchestration, identity/device registry, permissions and approvals, scheduler, audit/event coordination, Mosquitto MQTT, model gateway and ASUS TUF health routing, notifications, service discovery, and backup coordination. Home Assistant and PostgreSQL/pgvector remain conditional on measured safety, storage, RAM, and load acceptance. The Lenovo must not run Qwen3.5 4B, BGE-M3 inference, heavy STT/TTS, heavy vision/indexing, a local heavy LLM, or an unrestricted LLM shell.

Because the Lenovo has 4 GB RAM, installation remains minimal and headless. Configure swap only after disk and RAM inspection; admit Docker and services gradually from measured memory, disk, and load pressure. Require SMART monitoring, bounded logs, free-space thresholds, off-device backups, restore evidence, and staged stability gates. Do not add Redis, Kafka, Elasticsearch, Kubernetes, Prometheus, or Grafana without a later ADR and measured need.

### ASUS TUF — heavy compute and Windows execution plane

The ASUS TUF retains native Ollama, Qwen3.5 4B as the initial primary generation/orchestration/vision model, BGE-M3 embeddings, heavy speech/vision/indexing, the Windows satellite, isolated browser automation, development, benchmarking, and Codex work. Qwen3.5 9B is deferred, not an active required model, and not a Phase 4 or Phase 5A requirement. When the TUF is unavailable, Lenovo-hosted deterministic functions must degrade honestly rather than making the full backend appear dead.

### Desktop PC — future control-plane upgrade candidate

ADR-0005 and the owner-reported desktop hardware facts are preserved as historical evidence. The desktop PC is not the current deployment authority, active topology node, mandatory safety gate, or Phase 5B prerequisite. A future Lenovo-to-desktop migration requires a new owner-approved host-migration ADR and a separate safety gate.

## Historical branch boundary

- ADR-0003 remains historical and superseded by ADR-0005.
- ADR-0005 is superseded by ADR-0007.
- `phase-01/lenovo-foundation` remains unmerged audit history and must not be merged, rebased, force-pushed, rewritten, or reused.
- The new `phase-01/lenovo-control-plane-foundation` branch is the repository-side continuation from current `main`; physical Lenovo work remains separately owner-authorized.

## Verified sequencing state

- PR #7 merged into `main` at `caeb366af121ed3f2dca5239f34346a13f8a031a`.
- PR #8 merged into `main` at `a4a4cf78890c5efe98830a6ecc22757cf9f826f2`; Phase 4 is closed.
- PR #9 merged and closed into `main` at `7d0ec7aa957c5d3b33f4fc7818da0e5cc6382620`; Phase 5A is closed.
- PR #10 merged into `main` at `e8a2ddd6ecb4dac75b09fe6d96ec3071d270de41`; ADR-0007 is the accepted active architecture.
- The accepted active stack is Qwen3.5 4B plus BGE-M3 only. Qwen3.5 9B remains deferred.
- The accepted sequence is **architecture update restoring Lenovo → Lenovo G450 Safety Gate → Lenovo Ubuntu Server foundation → Phase 5B deployment/integration acceptance → Phase 6**.

## Verified Phase 2 and Phase 3 implementation state

- Phase 2 health, configuration, logging, SQLAlchemy/Alembic, PostgreSQL/pgvector Compose, and CI foundation are merged. GitHub CI is authoritative for the PostgreSQL path.
- Phase 3 pins OpenJarvis `1.0.0`, confines direct imports to the adapter, and verifies local-only request, bounded identifiers, trace redaction, contracts, and PostgreSQL integration. PR #5 is merged.

## Phase boundary

This Phase 1 update reconciles the repository with the owner-provided physical handoff and the authorized sanitized live checks. It does not reinstall Ubuntu, deploy containers, start Phase 5B, download models, change the Phase 5A gateway, alter database schema, or change model identities/digests. The remaining next step is completion and review of the Lenovo G450 Safety Gate.
