from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_phase_10_packages_are_importable() -> None:
    assert (ROOT / "scripts/__init__.py").is_file()
    assert (ROOT / "scripts/phase_10/__init__.py").is_file()


def test_enrollment_module_help_runs_without_hardware() -> None:
    completed = subprocess.run(
        [
            "uv",
            "run",
            "--python",
            "3.12",
            "--extra",
            "voice",
            "python",
            "-m",
            "scripts.phase_10.enroll_hey_jarvis_owner",
            "--help",
        ],
        capture_output=True,
        cwd=ROOT,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--base-calibration" in completed.stdout


def test_enrollment_launcher_uses_repo_root_module_execution() -> None:
    launcher = (ROOT / "scripts/phase_10/enroll_hey_jarvis_owner.ps1").read_text(encoding="utf-8")

    assert "Push-Location -LiteralPath $repo" in launcher
    assert "python -m scripts.phase_10.enroll_hey_jarvis_owner" in launcher
    assert "python (Join-Path $repo" not in launcher
    assert "Pop-Location" in launcher
