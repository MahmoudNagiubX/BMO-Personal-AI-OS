# BMO — Personal AI OS

A local-first, multimodal Personal AI Operating System with persistent memory, voice interaction, cross-device agents, room automation, and permission-controlled tool execution—built for Mahmoud's life, devices, projects, and room.

> **Current state:** Phase 3 is merged into `main`. Phase 4 is authorized on the ASUS TUF. The owner has replaced the Lenovo G450 with the desktop home server defined by ADR-0005. Phase 5A software-only model-gateway work may follow Phase 4 acceptance. After Phase 5A, physical deployment pauses for the Desktop Home Server Safety Gate before Phase 5B and Phase 6.

## Canonical documents

- [`docs/MASTER_PLAN.md`](docs/MASTER_PLAN.md) — architecture and full execution roadmap.
- [`AGENTS.md`](AGENTS.md) — mandatory coding-agent rules.
- [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md) — current verified state and next task.
- [`docs/adr/0005-desktop-server-control-plane.md`](docs/adr/0005-desktop-server-control-plane.md) — accepted always-on server decision, hardware baseline, maintenance policy, and migration plan.
- [`docs/CODEX_AGY_WORKFLOW.md`](docs/CODEX_AGY_WORKFLOW.md) — agent collaboration workflow.

## Locked foundations

- Python 3.12, FastAPI, PostgreSQL, pgvector, Flutter, and Docker Compose.
- OpenJarvis behind a replaceable product-owned adapter.
- Ollama with Qwen 3.5 4B, Qwen 3.5 9B, and BGE-M3 on the ASUS TUF.
- Ubuntu Server 24.04.4 LTS on the desktop home server as the always-on control plane.
- Home Assistant, Mosquitto MQTT, Pipecat, faster-whisper, openWakeWord, and local TTS.
- No required paid API or monthly software subscription.

## Device roles

### Desktop home server — always-on control plane

Owner-reported baseline:

- Ryzen 5 3600, 6 cores / 12 threads.
- B550 AORUS ELITE motherboard.
- 8 GB system RAM.
- GT 710 with 2 GB VRAM, retained for display and recovery—not AI inference.
- 128 GB SSD and approximately 350 GB HDD.
- Cooler Master 600 W power supply.

It will host the Core API, PostgreSQL/pgvector after health gates, Home Assistant, Mosquitto MQTT, scheduling, approvals, audit, backups, and TUF availability routing. It uses wired Ethernet, stock CPU settings, bounded logs, SMART monitoring, temperature monitoring, power-loss recovery, off-device backups, and 24-hour then seven-day stability gates.

Recommended first upgrades are 16 GB RAM, a 500 GB or larger SSD, and a UPS when practical.

### ASUS TUF — heavy compute and Windows execution

The ASUS TUF remains the Windows workstation and GPU node for Ollama, Qwen models, embeddings, heavy voice/vision/indexing, browser automation, the Windows satellite, development, and benchmarks.

### Lenovo status

The Lenovo G450 is removed from the active architecture. `phase-01/lenovo-foundation` and historical Lenovo references are retained only as audit history and must not be merged or used to authorize deployment.

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

AGY CLI is the default implementation agent for normal bounded tasks. Codex acts as the escalation agent for major architectural, security-sensitive, complex debugging, or cross-cutting work.

Read `docs/IMPLEMENTATION_STATUS.md` before every work session. Architecture changes require an accepted ADR, master-plan update, tests, and independent review.
