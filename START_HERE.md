# Start Here — First Repository Session

The architecture is finished. The first coding session is deliberately **Phase 0 validation**, not product implementation.

## 1. Clone the repository

```bash
git clone https://github.com/MahmoudNagiubX/BMO-Personal-AI-OS.git
cd BMO-Personal-AI-OS
git switch -c phase-00/repository-bootstrap
```

## 2. Start Codex

Launch Codex from the repository root, then paste the complete prompt from:

```text
docs/prompts/CODEX_PHASE_00.md
```

The task generates `uv.lock`, validates the bootstrap, runs checks, and creates the local Phase 0 report. It must not add product code.

## 3. Review the Codex diff

```bash
git diff --check
git diff
git status --short --ignored
```

Do not approve unexpected model, API, database, Flutter, MQTT, voice, or Home Assistant code.

## 4. Run AGY independent review

Launch `agy` from the same repository root. Keep permissions at `request-review` or `strict`, enable the terminal sandbox, and paste:

```text
docs/prompts/AGY_PHASE_00_REVIEW.md
```

AGY is read-only for this review. Return verified findings to Codex for narrow fixes.

## 5. Validate locally

```bash
uv run python scripts/check.py
uv run pre-commit run --all-files
```

## 6. Commit only after review

Suggested commit:

```bash
git add .
git status --short
git commit -m "chore(phase-00): validate repository governance baseline"
```

## Stop point

Do not install Ubuntu, create FastAPI code, add OpenJarvis, or pull AI models in this repository task. Those begin only after Phase 0 is accepted and Phase 1 is authorized in `docs/IMPLEMENTATION_STATUS.md`.
