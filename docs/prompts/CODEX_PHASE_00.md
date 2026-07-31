# Codex Escalation Prompt — Phase 0 Validation

Copy the prompt below into Codex from the repository root when escalating a major implementation or complex validation task.

---

You are implementing **Task P0-01: validate the Personal AI OS repository bootstrap**.

Before editing, read in this exact order:

1. `AGENTS.md`
2. `docs/IMPLEMENTATION_STATUS.md`
3. `docs/phases/PHASE_00_BOOTSTRAP.md`
4. Master-plan sections 0, 2, 4, 20 Phase 0, 22, 25, 28, 29, 34, and 35
5. `docs/adr/0001-architecture-baseline.md` through `0004-repository-license.md`

Then inspect the entire current repository.

Your scope is limited to Phase 0 governance/tooling files. Do not add product code or dependencies for FastAPI, PostgreSQL, OpenJarvis, Ollama, MQTT, Home Assistant, Flutter, voice, models, or satellites.

Tasks:

1. Check the generated files for contradictions, broken paths, invalid configuration, or unsafe defaults.
2. Generate `uv.lock` using Python 3.12-compatible resolution if it does not exist.
3. Run `uv sync --group dev --locked`.
4. Run `uv run python scripts/check.py`.
5. Fix only defects required for Phase 0 acceptance.
6. Run `uv run pre-commit run --all-files`.
7. Update `docs/IMPLEMENTATION_STATUS.md` with verified outcomes, but do not authorize Phase 1 unless all local Phase 0 criteria that do not require GitHub CI are complete.
8. Create `docs/phase_reports/PHASE_00_REPORT.md` with local evidence and mark GitHub/CI items pending when they have not occurred.
9. Stop. Do not begin Phase 1.

Do not commit, push, create a remote, or open a PR unless I explicitly ask after reviewing the diff.

Your final report must list:

- files changed;
- exact commands run and their exit status;
- tests/checks and actual results;
- security/data impact;
- unresolved Phase 0 items;
- confirmation that no later-phase code was added.

---
