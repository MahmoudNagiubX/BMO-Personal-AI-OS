$ErrorActionPreference = "Stop"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required. Install it through a trusted local process, then rerun this script."
}

uv python install 3.12
if (-not (Test-Path "uv.lock")) {
    uv lock
}
uv sync --group dev --locked
uv run pre-commit install
uv run python scripts/check.py

Write-Host "Bootstrap complete. Read docs/IMPLEMENTATION_STATUS.md before coding."
