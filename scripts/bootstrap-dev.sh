#!/usr/bin/env bash
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

uv python install 3.12
if [[ ! -f uv.lock ]]; then
  uv lock
fi
uv sync --group dev --locked
uv run pre-commit install
uv run python scripts/check.py

echo "Bootstrap complete. Read docs/IMPLEMENTATION_STATUS.md before coding."
