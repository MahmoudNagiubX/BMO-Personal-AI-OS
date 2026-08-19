# Implementation Status

> This file records verified repository state, owner-approved architecture, and the current sanitized VENOM physical-gate evidence. The Lenovo 24-hour and seven-day observation windows remain real-time evidence, not manually asserted success states.

- **Plan baseline:** 1.6 — 2026-08-19
- **Current phase boundary:** Phase 5B and Phase 6 are merged. Phase 7 text-first conversation and clients, including lifecycle/WebSocket recovery, are implemented on `phase-07/text-first-conversation-clients` and ready for independent review after exact-head CI; Phase 8 is `NOT_STARTED`.
- **Current state:** PR #9 is merged and Phase 5A is closed; the PR #14 Phase 1 Lenovo/VENOM repository foundation and owner-waiver baseline and PR #15 Phase 5B deployment acceptance are merged. Exact Phase 5B security-fix commit `e902e85dc6651d63f536a34516b31eb29c778b5c` remains deployed. Phase 6 identity/device enrollment is merged, and Phase 7 adds only repository/CI text conversation boundaries; neither Phase 6 nor Phase 7 has been persistently deployed to VENOM.
- **Current evidence:** Live identity, Ethernet route, thermal peak, bounded memory, dedicated key login, privileged hardening, SMART, scoped UFW, bounded journald, encrypted backup/restore, reboot recovery, and the official stability marker are recorded in `infrastructure/home_server/evidence/venom_physical_gate.json`.
- **Current branch target:** `phase-07/text-first-conversation-clients` on a draft PR; do not merge without independent review and owner approval.
- **Measured stability:** 24-hour `WAITING / WAIVED_AS_BLOCKING_PREREQUISITE / still monitoring`; seven-day `WAITING / WAIVED_AS_BLOCKING_PREREQUISITE / still monitoring`. These are not stability PASS states.
- **Later phases authorized:** ADR-0008 historically recorded Phase 5B as `AUTHORIZED_TO_START`. Phase 6 was separately owner-authorized after the Phase 5B merge and is merged. Phase 7 is separately owner-authorized and repository-implemented for independent review, including the accepted lifecycle/WebSocket recovery. Phase 8 remains `NOT_STARTED`.

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

The authorized closeout recovery installed and verified SMART tooling, denied
root SSH while retaining password recovery and key authentication, scoped UFW
to `192.162.1.0/24`, bounded journald, installed the durable root scalar
monitor, proved encrypted off-device backup and temporary restore, and verified
one controlled reboot. The preliminary marker and official markers at
`2026-08-18T22:28:46Z` and `2026-08-18T23:29:53Z` are preserved as superseded
history. The FINAL real-time stability marker began at `2026-08-19T00:11:05Z`
UTC with boot ID `0722b8e8-1c8c-4268-83f8-eeda51724308`. The new monitor records SMART sector
counters 5, 197, and 198 without serials or raw SMART output. The encrypted
backup is persistent outside Git on the ASUS TUF, and the effective lid policy
is `ignore` for lid, external power, and docked operation.

The real evaluator at `scripts/phase_01/evaluate_stability_gate.py` derives
WAITING_FOR_24H, WAITING_FOR_7D, BLOCKED, or PASS from the official marker and
sanitized monitor samples. At the 24-hour and seven-day boundaries it requires
leading, adjacent, and trailing timestamp gaps of at most 1,860 seconds, plus
75% minimum 15-minute coverage and zero SMART sector counters. Small stable
residual swap is allowed; only three consecutive samples at or above 256 MiB
block as sustained pressure. Malformed sample data returns `BLOCKED`; manually
edited status strings are never trusted.

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
- PR #15 merged into `main` at `a3c698a9cc8dd7fbedd69fc1e3f73c134c6e41c2`; Phase 5B is closed.
- The accepted active stack is Qwen3.5 4B plus BGE-M3 only. Qwen3.5 9B remains deferred.
- The accepted sequence is **architecture update restoring Lenovo → Lenovo G450 Safety Gate → Lenovo Ubuntu Server foundation → Phase 5B deployment/integration acceptance → Phase 6 identity/device enrollment → Phase 7**. The measured stability gates remain waiting under ADR-0008 and background monitoring remains active. Phase 6 is merged; Phase 7 is ready for independent review; Phase 8 is `NOT_STARTED`.

## Verified Phase 2 and Phase 3 implementation state

- Phase 2 health, configuration, logging, SQLAlchemy/Alembic, PostgreSQL/pgvector Compose, and CI foundation are merged. GitHub CI is authoritative for the PostgreSQL path.
- Phase 3 pins OpenJarvis `1.0.0`, confines direct imports to the adapter, and verifies local-only request, bounded identifiers, trace redaction, contracts, and PostgreSQL integration. PR #5 is merged.

## Phase boundary

Phase 7 adds durable text conversations, device-bound sessions, authenticated REST and WebSocket event replay, idempotent submissions, serialized runs, truthful cancellation, restart reconciliation, verified Qwen3.5 4B responses, and a minimal text client. It does not physically deploy PostgreSQL/Core API to VENOM, change Phase 5B model/tunnel behavior, add public exposure, execute tools, add memory/RAG, or start Phase 8. Background Phase 1 monitoring remains actionable: SMART overall failure, any SMART counters 5/197/198 above zero, repeated thermal breach, root-filesystem pressure, unexpected reboot patterns, repeated failed units, or repeated Ethernet management-path loss pause deployment expansion and require reporting.
