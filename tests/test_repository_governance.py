from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from scripts.verify_governance import REQUIRED_FILES, ROOT, validate


def test_repository_root_is_correct() -> None:
    assert (ROOT / "AGENTS.md").is_file()
    assert Path(__file__).resolve().parents[1] == ROOT


def test_all_required_governance_files_exist() -> None:
    missing = [rel for rel in REQUIRED_FILES if not (ROOT / rel).is_file()]
    assert missing == []


def test_governance_validation_passes() -> None:
    assert validate() == []


def test_real_env_file_is_ignored() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env\n" in gitignore
    assert "!.env.example" in gitignore


def test_bootstrap_scripts_do_not_execute_remote_installers() -> None:
    for script in ("scripts/bootstrap-dev.ps1", "scripts/bootstrap-dev.sh"):
        content = (ROOT / script).read_text(encoding="utf-8")
        assert "astral.sh/uv/install" not in content


def test_lenovo_bootstrap_script_safety() -> None:
    script_path = ROOT / "infrastructure/lenovo-server/bootstrap.sh"
    assert script_path.is_file()
    content = script_path.read_text(encoding="utf-8")
    lowercase_content = content.lower()

    if bash := shutil.which("bash"):
        try:
            bash_available = (
                subprocess.run(
                    [bash, "--version"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=2,
                ).returncode
                == 0
            )
        except subprocess.TimeoutExpired:
            bash_available = False
        if bash_available:
            result = subprocess.run(
                [bash, "-n", str(script_path)],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            assert result.returncode == 0, result.stderr

    assert "--preflight" in content
    assert "--apply" in content
    assert "BMO_LENOVO_BOOTSTRAP_CONFIRM=YES" in content
    assert "curl | sh" not in lowercase_content
    assert "wget | sh" not in lowercase_content
    for destructive_command in ("mkfs", "fdisk", "parted", "wipefs", "dd if="):
        assert destructive_command not in lowercase_content
    assert "passwordauthentication no" not in lowercase_content
    assert "tcp://" not in lowercase_content
    assert "0.0.0.0:2375" not in lowercase_content
    assert "0.0.0.0:2376" not in lowercase_content
    assert "max-size" in content
    assert "max-file" in content
    assert "PermitRootLogin no" in content
    assert "PubkeyAuthentication yes" in content


def test_ci_workflow_triggers_and_permissions() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "pull_request:" in workflow
    assert "contents: read" in workflow
    assert "contents: write" not in workflow
    assert "git commit" not in workflow
    assert "git push" not in workflow
    assert "git add" not in workflow


def test_agent_governance_roles_and_escalation_rules() -> None:
    agents_content = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "AGY CLI is the default implementation agent" in agents_content
    assert "Codex is the escalation agent" in agents_content

    workflow_content = (ROOT / "docs/CODEX_AGY_WORKFLOW.md").read_text(encoding="utf-8")
    assert "## Codex Escalation Handoff" in workflow_content
    assert "never edit the same files" in workflow_content
    assert "explicitly authorized" in workflow_content

    status_content = (ROOT / "docs/IMPLEMENTATION_STATUS.md").read_text(encoding="utf-8")
    assert "- **Later phases authorized:** No" in status_content
