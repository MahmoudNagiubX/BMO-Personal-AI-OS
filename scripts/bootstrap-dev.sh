#!/usr/bin/env bash
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install it through a trusted local process, then rerun this script." >&2
  exit 1
fi

uv python install 3.12
if [[ ! -f uv.lock ]]; then
  uv lock
fi
uv sync --group dev --locked
uv run pre-commit install
uv run python scripts/check.py

echo "Bootstrap complete. Read docs/IMPLEMENTATION_STATUS.md before coding."
