# BMO — Personal AI OS

A local-first, multimodal Personal AI Operating System with persistent memory, voice interaction, cross-device agents, room automation, and permission-controlled tool execution—built for Mahmoud's life, devices, projects, and room.

> **Current state:** Phase 4 and Phase 5A are closed. ADR-0007 merged through PR #10; repository cleanup PR #11 merged at `09593cc1874d997fb4888db326068112cf0afd7f`. Plan v1.3 / ADR-0008 document the future typed observation, provenance, world-state, and advanced-context architecture without starting those systems. The current mandatory physical boundary remains the Lenovo G450 Safety Gate and Ubuntu Server 24.04.4 LTS AMD64 Foundation; Phase 5B and Phase 6 remain blocked.

## Canonical documents

- [`docs/MASTER_PLAN.md`](docs/MASTER_PLAN.md) — architecture and full execution roadmap.
- [`AGENTS.md`](AGENTS.md) — mandatory coding-agent rules.
- [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md) — current verified state and next task.
- [`docs/adr/0007-restore-lenovo-temporary-control-plane.md`](docs/adr/0007-restore-lenovo-temporary-control-plane.md) — accepted temporary control-plane decision, resource policy, and migration plan.
- [`docs/adr/0008-advanced-context-architecture.md`](docs/adr/0008-advanced-context-architecture.md) — accepted future typed observation/evidence and non-authoritative World State architecture; no current implementation authorization.
- [`docs/CODEX_WORKFLOW.md`](docs/CODEX_WORKFLOW.md) — current implementation and independent-review workflow.

## Locked foundations

- Python 3.12, FastAPI, PostgreSQL, pgvector, Flutter, and Docker Compose.
- OpenJarvis behind a replaceable product-owned adapter.
- Ollama with Qwen 3.5 4B as the initial primary model and BGE-M3 embeddings on the ASUS TUF; Qwen 3.5 9B is deferred.
- Ubuntu Server 24.04.4 LTS AMD64, headless with no GUI, on the temporary Lenovo G450 control plane.
- Home Assistant, Mosquitto MQTT, Pipecat, faster-whisper, openWakeWord, and local TTS.
- Typed tools, explicit approvals, provenance-backed observations, explicit source authority/freshness/conflict semantics, and no unrestricted shell.
- No required paid API or monthly software subscription.

## Advanced context architecture

ADR-0008 accepts a common future evidence boundary for contextual capabilities. It separates evidence quality from freshness and conflict state, keeps World State as a permission-aware read model rather than a second authority, requires deterministic semantic fusion first, and limits agent runtimes to bounded context snapshots.

The documented future capability families include World State, context fusion, active workspace context, engineering/scientific workflows, bounded long-horizon goals, explicit active perception, safe physical agents, anomaly intelligence, communications, adaptive personalization, distributed resilience, and spatial/AR interfaces. They remain future-gated; this architecture update creates no new service, API, database migration, dependency, robot, camera monitor, mobile model, or AR runtime.

## Device roles

### Lenovo G450 — temporary lightweight always-on control plane

Established planning baseline:

- Core 2 Duo class CPU; the exact model remains subject to physical verification.
- 4 GB RAM and approximately 128 GB internal storage recorded for planning; exact disk type/model remains subject to physical verification.
- Physical RJ-45 Ethernet.
- No useful AI GPU and no local heavy model.

It may host the Core API, identity, approvals, scheduler, audit/event coordination, Mosquitto MQTT, model-gateway/TUF health routing, notifications, service discovery, and backup coordination. Home Assistant and PostgreSQL/pgvector are conditional on measured safety, storage, RAM, and load acceptance. It uses Ubuntu Server 24.04.4 LTS AMD64 headlessly, private-LAN services, SSH, wired Ethernet, bounded logs, SMART monitoring, backups, and 24-hour then seven-day stability gates.

No final swap size is set before inspection. Docker and services are admitted gradually from measured memory and disk pressure; Redis, Kafka, Elasticsearch, Kubernetes, Prometheus, and Grafana require a later ADR and measured need. ADR-0008 adds no Lenovo service now; heavy perception/high-rate fusion/model work remains on the TUF or owning device.

### ASUS TUF — heavy compute and Windows execution

The ASUS TUF remains the Windows workstation and GPU node for Ollama, Qwen models, embeddings, heavy voice/vision/indexing, future heavy perception, browser automation, the Windows satellite, development, and benchmarks.

### Desktop PC status

The desktop PC is retained as a future control-plane upgrade or migration candidate. Its hardware records and ADR-0005 are preserved as historical evidence; it is not an active required node or Phase 5B prerequisite.

### Historical branch boundary

`phase-01/lenovo-foundation` remains audit history and must not be merged, rebased, force-pushed, rewritten, or reused. After this documentation-only architecture PR is independently reviewed and owner-merged, physical Lenovo work starts from then-current `main` on a new `phase-01/lenovo-control-plane-foundation` branch.

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
