# BMO — Personal AI OS

A local-first, multimodal Personal AI Operating System with persistent memory, voice interaction, cross-device agents, room automation, and permission-controlled tool execution—built for Mahmoud's life, devices, projects, and room.

> **Current state:** Phase 5B through Phase 9 are merged and the ASUS TUF physical Windows satellite gate passed. VENOM was restored to its accepted baseline. Phase 10 JARVIS Voice Core is owner-authorized on `phase-10/jarvis-voice-core`; Phase 11 room/multi-device voice remains `NOT_STARTED`.

## Canonical documents

- [`docs/MASTER_PLAN.md`](docs/MASTER_PLAN.md) — architecture and full execution roadmap.
- [`AGENTS.md`](AGENTS.md) — mandatory coding-agent rules.
- [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md) — current verified state and next task.
- [`docs/phases/PHASE_10_JARVIS_VOICE_CORE.md`](docs/phases/PHASE_10_JARVIS_VOICE_CORE.md) — single-device JARVIS voice scope and acceptance boundary.
- [`docs/phases/PHASE_11_ROOM_MULTI_DEVICE_VOICE.md`](docs/phases/PHASE_11_ROOM_MULTI_DEVICE_VOICE.md) — deferred room/multi-device voice boundary.
- [`docs/adr/0011-jarvis-voice-architecture-v2.md`](docs/adr/0011-jarvis-voice-architecture-v2.md) — accepted v2 JARVIS activation, turn-taking, and Phase 10/11 boundary.
- [`docs/phases/PHASE_01_LENOVO_CONTROL_PLANE_FOUNDATION.md`](docs/phases/PHASE_01_LENOVO_CONTROL_PLANE_FOUNDATION.md) — current Phase 1 scope and safety boundary.
- [`docs/phase_reports/PHASE_01_LENOVO_FOUNDATION_REPORT.md`](docs/phase_reports/PHASE_01_LENOVO_FOUNDATION_REPORT.md) — in-progress evidence and validation record.
- [`docs/adr/0007-restore-lenovo-temporary-control-plane.md`](docs/adr/0007-restore-lenovo-temporary-control-plane.md) — accepted temporary control-plane decision, resource policy, and migration plan.
- [`docs/CODEX_WORKFLOW.md`](docs/CODEX_WORKFLOW.md) — current implementation and independent-review workflow.

## Locked foundations

- Python 3.12, FastAPI, PostgreSQL, pgvector, Flutter, and Docker Compose.
- OpenJarvis behind a replaceable product-owned adapter.
- Ollama with Qwen 3.5 4B as the initial primary model and BGE-M3 embeddings on the ASUS TUF; Qwen 3.5 9B is deferred.
- Ubuntu Server 24.04.4 LTS AMD64, headless with no GUI, on the temporary Lenovo G450 control plane.
+ Local JARVIS voice on the ASUS TUF uses one pinned official openWakeWord Hey Jarvis candidate plus a bounded local faster-whisper exact-prefix verifier, with double-Right-Ctrl activation, Pipecat Smart Turn, Silero VAD, and local TTS; the software gate must pass before owner physical acceptance and room voice remains Phase 11. Prior bare-`Jarvis` and rejected candidates remain historical evidence.
- No required paid API or monthly software subscription.

## Device roles

### Lenovo G450 — temporary lightweight always-on control plane

Verified physical handoff baseline:

- Core 2 Duo class CPU, verified as Intel Core 2 Duo T6500 with 2 cores.
- Approximately 4 GiB RAM.
- `/dev/sda`, Seagate ST9320325AS, approximately 298 GiB.
- Physical RJ-45 Ethernet.
- No useful AI GPU and no local heavy model.
- Hostname `venom-server`, Linux user `venom`, and Ubuntu Server 24.04.4 LTS AMD64.

It may host the Core API, identity, approvals, scheduler, audit/event coordination, Mosquitto MQTT, model-gateway/TUF health routing, notifications, service discovery, and backup coordination. Home Assistant and PostgreSQL/pgvector are conditional on measured safety, storage, RAM, and load acceptance. It uses Ubuntu Server 24.04.4 LTS AMD64 headlessly, private-LAN services, SSH, wired Ethernet, bounded logs, SMART monitoring, backups, and 24-hour then seven-day stability gates.

The owner-provided handoff records SSH reachability, UFW enabled with SSH allowed, clean SMART evidence, and the manual `~/venom` proof-of-life. Ethernet, memory, thermal, power, hardening, backup/restore, reboot, and stability gates remain incomplete.

No final swap size is set before inspection. Docker and services are admitted gradually from measured memory and disk pressure; Redis, Kafka, Elasticsearch, Kubernetes, Prometheus, and Grafana require a later ADR and measured need.

### ASUS TUF — heavy compute and Windows execution

The ASUS TUF remains the Windows workstation and GPU node for Ollama, Qwen models, embeddings, heavy voice/vision/indexing, browser automation, the Windows satellite, development, and benchmarks.

### Desktop PC status

The desktop PC is retained as a future control-plane upgrade or migration candidate. Its hardware records and ADR-0005 are preserved as historical evidence; it is not an active required node or Phase 5B prerequisite.

### Historical branch boundary

`phase-01/lenovo-foundation` remains audit history and must not be merged, rebased, force-pushed, rewritten, or reused. This repository-side foundation uses the new `phase-01/lenovo-control-plane-foundation` branch from current `main`; physical work remains a separate owner-authorized safety-gate activity.

## Bootstrap

Install `uv` through a trusted local process before running these scripts. They do not download or execute an installer.

Linux/macOS/WSL:

```bash
./scripts/bootstrap-dev.sh
```

Windows PowerShell:

```powershell
./scripts/bootstrap-dev.ps1
```

Manual:

```bash
uv python install 3.12
uv lock
uv sync --group dev --locked
uv run python scripts/check.py
```

`make check` is an optional shorthand on systems with Make.

## Local development

```powershell
uv sync --group dev --locked
Copy-Item .env.example .env
docker compose -f compose.dev.yml up -d
uv run alembic upgrade head
uv run uvicorn personal_ai_os.app:create_app --factory --host 127.0.0.1 --port 8000
uv run python scripts/check.py
docker compose -f compose.dev.yml down
```

The API and PostgreSQL development service bind to localhost only. Keep `.env` local and use synthetic development credentials.

## Agent workflow

Codex is the default implementation specialist. Independent review is read-only and required before owner merge; Mahmoud is the sole merge and architecture approval authority.

Read `docs/IMPLEMENTATION_STATUS.md` before every work session. Architecture changes require an accepted ADR, master-plan update, tests, and independent review.
