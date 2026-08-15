# Contributing

## Before work

1. Read `AGENTS.md`.
2. Read `docs/CODEX_AGY_WORKFLOW.md`.
3. Read `docs/IMPLEMENTATION_STATUS.md`.
4. Read the current phase specification.
5. Read every accepted or superseding ADR relevant to the task.
6. Create a branch named `phase-XX/short-description`.

## Scope

Changes must stay inside the assigned phase. Architecture changes require an ADR, a master-plan update, migration and rollback notes, implementation-status changes, tests, and independent review.

The Lenovo G450 defined by ADR-0007 is the temporary lightweight always-on control plane. The desktop PC is a future upgrade candidate. `phase-01/lenovo-foundation` remains historical and must not be reused; future physical Lenovo work begins only after owner merge on a new `phase-01/lenovo-control-plane-foundation` branch.

## Development

```bash
uv sync --group dev --locked
uv run python scripts/check.py
```

Use Python 3.12. Keep changes typed, tested, documented, and security-reviewed.

## Commits

```text
feat(phase-02): add core API health endpoint
fix(phase-09): reject unregistered executable paths
test(phase-08): cover expired approval denial
docs(phase-01): add home-server recovery runbook
```

## Pull requests

Include:

- What and why.
- Exact scope.
- Security and data impact.
- Tests and command output.
- Migration and rollback.
- Master-plan or ADR changes.
- Hardware evidence versus owner-reported assumptions when physical systems are involved.

Do not include secrets, real private data, generated database files, or unrelated changes.
