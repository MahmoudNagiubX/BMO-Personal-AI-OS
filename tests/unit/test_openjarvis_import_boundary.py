"""AST enforcement for the product/OpenJarvis import boundary."""

from __future__ import annotations

import ast
from pathlib import Path


def _forbidden_imports(source: str, relative_path: str) -> list[str]:
    tree = ast.parse(source, filename=relative_path)
    violations: list[str] = []
    allowed_prefix = "packages/openjarvis_adapter/"
    for node in ast.walk(tree):
        imported_names: list[str] = []
        if isinstance(node, ast.Import):
            imported_names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_names = [node.module]
        if any(
            name == "openjarvis" or name.startswith("openjarvis.") for name in imported_names
        ) and not relative_path.replace("\\", "/").startswith(allowed_prefix):
            violations.append(relative_path)
    return violations


def test_repository_has_no_direct_openjarvis_import_outside_adapter() -> None:
    repository = Path(__file__).resolve().parents[2]
    violations: list[str] = []
    for root_name in ("src", "packages", "scripts", "tests"):
        root = repository / root_name
        for path in root.rglob("*.py"):
            relative = path.relative_to(repository).as_posix()
            violations.extend(_forbidden_imports(path.read_text(encoding="utf-8"), relative))
    assert violations == []


def test_boundary_parser_catches_forbidden_negative_fixture() -> None:
    source = "from openjarvis import Jarvis\n"
    assert _forbidden_imports(source, "src/personal_ai_os/forbidden_fixture.py") == [
        "src/personal_ai_os/forbidden_fixture.py"
    ]
