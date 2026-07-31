"""Run the repository validation suite with clear fail-fast output."""

from __future__ import annotations

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
    run("Pytest", ["uv", "run", "pytest"])
    run("Governance and secret guard", ["uv", "run", "python", "scripts/verify_governance.py"])
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
