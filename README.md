# BMO — Personal AI OS

A local-first, multimodal Personal AI Operating System with persistent memory, voice interaction, cross-device agents, room automation, and permission-controlled tool execution—built for Mahmoud's life, devices, projects, and room.

> **Current state:** Phase 2 technical acceptance criteria are satisfied on PR #4. Lenovo hardware acceptance remains deferred, and owner merge remains pending.

## Canonical documents

- [`docs/MASTER_PLAN.md`](docs/MASTER_PLAN.md) — architecture and full execution roadmap.
- [`AGENTS.md`](AGENTS.md) — mandatory coding-agent rules.
- [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md) — current verified state and next task.
- [`docs/phases/PHASE_00_BOOTSTRAP.md`](docs/phases/PHASE_00_BOOTSTRAP.md) — current phase contract.
- [`docs/CODEX_AGY_WORKFLOW.md`](docs/CODEX_AGY_WORKFLOW.md) — agent collaboration workflow.

## Locked foundations

- Python 3.12, FastAPI, PostgreSQL, pgvector, Flutter, Docker Compose.
- OpenJarvis behind a replaceable adapter.
- Ollama with Qwen 3.5 4B, Qwen 3.5 9B, and BGE-M3 on the ASUS TUF.
- Ubuntu Server on the Lenovo G450 as the always-on control plane.
- Home Assistant, Mosquitto MQTT, Pipecat, faster-whisper, openWakeWord, and local TTS.
- No required paid API or monthly software subscription.

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

## Phase 2 local development

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

See [`docs/CODEX_AGY_WORKFLOW.md`](docs/CODEX_AGY_WORKFLOW.md) for full roles, permission defaults, escalation triggers, and review requirements.

## Status

Read `docs/IMPLEMENTATION_STATUS.md` before every work session. Do not begin Phase 1 until Phase 0 acceptance is verified and recorded.
