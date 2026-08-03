"""Run the repository validation suite with clear fail-fast output."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence


def run(label: str, command: Sequence[str]) -> None:
    print(f"\n==> {label}")
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        print(f"FAILED: {label}", file=sys.stderr)
        raise SystemExit(completed.returncode)


def main() -> None:
    run("Ruff lint", ["uv", "run", "ruff", "check", "."])
    run("Ruff formatting", ["uv", "run", "ruff", "format", "--check", "."])
    run("Mypy", ["uv", "run", "mypy"])
    pytest_command = ["uv", "run", "pytest"]
    if os.environ.get("BMO_TEST_DATABASE_URL"):
        pytest_label = "Pytest (unit and integration)"
    else:
        pytest_command.extend(["-m", "not integration"])
        pytest_label = "Pytest (non-integration; PostgreSQL integration skipped)"
        print("PostgreSQL integration tests skipped: BMO_TEST_DATABASE_URL is not set.")
    run(pytest_label, pytest_command)
    run("Governance and secret guard", ["uv", "run", "python", "scripts/verify_governance.py"])
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
