# Contributing

## Before work

1. Read `AGENTS.md`.
2. Read `docs/IMPLEMENTATION_STATUS.md`.
3. Read the current phase specification.
4. Create a branch named `phase-XX/short-description`.

## Scope

Changes must stay inside the assigned phase. Architecture changes require an ADR and a master-plan update.

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
docs(phase-01): add Lenovo recovery runbook
```

## Pull requests

Include:

- What and why.
- Exact scope.
- Security and data impact.
- Tests and command output.
- Migration and rollback.
- Master-plan or ADR changes.

Do not include secrets, real private data, generated database files, or unrelated changes.
