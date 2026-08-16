"""Validate source-of-truth files and reject obvious secret/data leaks."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = (
    "START_HERE.md",
    "AGENTS.md",
    "README.md",
    "LICENSE",
    "SECURITY.md",
    "CONTRIBUTING.md",
    ".env.example",
    ".gitignore",
    ".pre-commit-config.yaml",
    "pyproject.toml",
    "uv.lock",
    ".github/workflows/ci.yml",
    "docs/MASTER_PLAN.md",
    "docs/IMPLEMENTATION_STATUS.md",
    "docs/CODEX_WORKFLOW.md",
    "docs/phases/PHASE_00_BOOTSTRAP.md",
    "docs/phases/PHASE_04_TUF_MODEL_NODE.md",
    "docs/phases/PHASE_05A_MODEL_GATEWAY.md",
    "docs/adr/ADR_TEMPLATE.md",
    "docs/adr/0001-architecture-baseline.md",
    "docs/adr/0002-openjarvis-adapter.md",
    "docs/adr/0003-compute-control-split.md",
    "docs/adr/0004-repository-license.md",
    "docs/adr/0005-desktop-server-control-plane.md",
    "docs/adr/0006-initial-model-stack.md",
    "docs/adr/0007-restore-lenovo-temporary-control-plane.md",
    "docs/adr/0008-advanced-context-architecture.md",
    "docs/legal/LICENSE_INVENTORY.md",
    "docs/legal/THIRD_PARTY_NOTICES.md",
    "docs/phase_reports/PHASE_04_REPORT.md",
    "docs/phase_reports/PHASE_05A_REPORT.md",
)

FORBIDDEN_BASENAMES = {
    ".env",
    "id_rsa",
    "id_ed25519",
    "credentials.json",
    "service-account.json",
}

FORBIDDEN_SUFFIXES = {
    ".pem",
    ".p12",
    ".pfx",
    ".jks",
    ".keystore",
    ".sqlite",
    ".sqlite3",
    ".dump",
    ".backup",
}

SKIP_PARTS = {".git", ".venv", ".pytest_cache", ".mypy_cache", ".ruff_cache"}

SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{30,}\b"),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
}

TEXT_SUFFIXES = {
    "",
    ".md",
    ".txt",
    ".py",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".ini",
    ".cfg",
    ".sh",
    ".ps1",
    ".example",
}


def repository_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        files.append(path)
    return files


def validate() -> list[str]:
    errors: list[str] = []

    for required_file in REQUIRED_FILES:
        if not (ROOT / required_file).is_file():
            errors.append(f"Missing required file: {required_file}")

    master_plan = ROOT / "docs/MASTER_PLAN.md"
    if master_plan.is_file():
        text = master_plan.read_text(encoding="utf-8")
        required_phrases = (
            "Status:** Locked baseline",
            "Plan version:** 1.3",
            "OpenJarvis",
            "Qwen 3.5 4B",
            "Lenovo G450",
            "Ubuntu Server 24.04.4 LTS",
            "Advanced Context, Intelligence, and Embodiment Layer",
            "Typed observation and evidence foundation — ADR-0008",
            "# 34. First Implementation Order",
        )
        for phrase in required_phrases:
            if phrase not in text:
                errors.append(f"Master plan is missing locked phrase: {phrase}")

    for path in repository_files():
        relative_path = path.relative_to(ROOT)
        if path.name in FORBIDDEN_BASENAMES:
            errors.append(f"Forbidden sensitive filename: {relative_path}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"Forbidden sensitive file type: {relative_path}")
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"Makefile", "LICENSE"}:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                errors.append(f"Potential {name} found in {relative_path}")

    return errors


def main() -> None:
    errors = validate()
    if errors:
        print("Repository governance validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        raise SystemExit(1)
    print("Repository governance validation passed.")


if __name__ == "__main__":
    main()
