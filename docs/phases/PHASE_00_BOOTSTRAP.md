# Phase 0 — Repository Bootstrap Contract

## Goal

Establish a safe, reproducible source-of-truth repository before any product implementation.

## In scope

- Governance documents.
- Agent instructions.
- ADR baseline.
- Legal/license inventory.
- Secret and personal-data exclusions.
- Python 3.12 development-tool environment.
- Repository validation scripts and tests.
- CI for the skeleton.
- Issue and PR templates.
- Phase status and report format.

## Explicitly out of scope

Do not add or implement:

- FastAPI application code.
- PostgreSQL or pgvector services.
- OpenJarvis package dependency or adapter code.
- Ollama/model code.
- Device enrollment.
- Windows satellite.
- Voice, Flutter, Home Assistant, MQTT, life modules, browser automation, or animations.
- Lenovo provisioning scripts beyond documentation placeholders.

Those belong to later phases.

## Task P0-01 — Validate the generated bootstrap

1. Inspect every generated file for consistency with the master plan.
2. Generate and commit `uv.lock` from `pyproject.toml`.
3. Run a clean development bootstrap.
4. Fix only Phase 0 defects.
5. Ensure formatting, lint, typing, tests, and governance validation pass.

## Task P0-02 — GitHub baseline

1. Confirm the intended GitHub remote.
2. Work from branch `phase-00/repository-bootstrap`.
3. Confirm no ignored or sensitive files are staged.
4. Create a reviewed Phase 0 PR.

Git push and PR creation require explicit owner approval.

## Task P0-03 — Validate CI

1. Push the reviewed branch.
2. Confirm CI runs from a clean GitHub environment.
3. Fix only reproducibility/governance failures.
4. Record final evidence.

## Required commands

```bash
uv python install 3.12
uv lock
uv sync --group dev --locked
uv run python scripts/check.py
git status --short --ignored
```

Optional pre-commit check:

```bash
uv run pre-commit run --all-files
```

## Acceptance criteria

- All required governance files exist.
- `uv.lock` is committed.
- A clean clone can bootstrap with documented commands.
- Full check succeeds.
- CI succeeds.
- Secret/data guard succeeds.
- No product dependencies or code were introduced.
- ADRs match the master plan.
- Phase report exists.
- Status explicitly authorizes or blocks Phase 1.

## Phase report

Create:

```text
docs/phase_reports/PHASE_00_REPORT.md
```

Include environment, commands, outcomes, CI link/status, security check, known limitations, rollback, commit SHA, and the next authorized task.
