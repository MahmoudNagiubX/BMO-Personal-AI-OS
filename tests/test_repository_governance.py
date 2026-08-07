from __future__ import annotations

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


def test_desktop_server_architecture_is_locked() -> None:
    status_content = (ROOT / "docs/IMPLEMENTATION_STATUS.md").read_text(encoding="utf-8")
    master_plan = (ROOT / "docs/MASTER_PLAN.md").read_text(encoding="utf-8")
    agents_content = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    accepted_adr = (ROOT / "docs/adr/0005-desktop-server-control-plane.md").read_text(
        encoding="utf-8"
    )
    superseded_adr = (ROOT / "docs/adr/0003-compute-control-split.md").read_text(encoding="utf-8")

    assert "ADR-0005 is the active host decision" in master_plan
    assert "Xubuntu 24.04 LTS" in master_plan
    assert "Ryzen 5 3600" in master_plan
    assert "8 GB system RAM" in master_plan
    assert "GT 710" in master_plan
    assert "128 GB SSD" in master_plan
    assert "Cooler Master 600 W power supply" in master_plan
    assert "Desktop Home Server Safety Gate" in status_content
    assert "Phase 4 technical acceptance is complete" in status_content
    assert "The Lenovo G450 is removed from active architecture" in status_content
    assert "desktop home server defined by ADR-0005" in agents_content
    assert "Qwen 3.5 4B is the initial primary" in agents_content
    assert "Qwen 3.5 9B is deferred" in agents_content
    assert "services do not depend on a GUI login" in agents_content
    assert "**Status:** Accepted" in accepted_adr
    assert "**Supersedes:** ADR-0003" in accepted_adr
    assert "two-year always-on service window is accepted" in accepted_adr
    assert "**Status:** Superseded" in superseded_adr
    assert "**Superseded by:** ADR-0005" in superseded_adr
    model_adr = (ROOT / "docs/adr/0006-initial-model-stack.md").read_text(encoding="utf-8")
    assert "Qwen3.5 4B as the initial local model" in model_adr
    assert "Qwen3.5 9B is deferred" in model_adr


def test_phase_four_active_manifest_and_closeout_docs_exclude_9b() -> None:
    manifest = (ROOT / "infrastructure/tuf/model_manifest.json").read_text(encoding="utf-8")
    phase_spec = (ROOT / "docs/phases/PHASE_04_TUF_MODEL_NODE.md").read_text(encoding="utf-8")
    report = (ROOT / "docs/phase_reports/PHASE_04_REPORT.md").read_text(encoding="utf-8")

    assert '"role": "primary"' in manifest
    assert '"role": "embeddings"' in manifest
    assert "qwen3.5:9b" not in manifest
    assert "No model gateway" in phase_spec
    assert "PHASE 4 ACCEPTED locally" in report
    assert "not required" in report


def test_retired_lenovo_branch_is_not_an_active_deployment_target() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    status_content = (ROOT / "docs/IMPLEMENTATION_STATUS.md").read_text(encoding="utf-8")
    master_plan = (ROOT / "docs/MASTER_PLAN.md").read_text(encoding="utf-8")

    assert "must not be merged" in readme
    assert "phase-01/home-server-foundation" in status_content
    assert "Do not merge or deploy the retired Lenovo branch" in master_plan


def test_active_architecture_has_no_stale_ubuntu_or_dual_model_requirements() -> None:
    master_plan = (ROOT / "docs/MASTER_PLAN.md").read_text(encoding="utf-8")
    status_content = (ROOT / "docs/IMPLEMENTATION_STATUS.md").read_text(encoding="utf-8")

    assert (
        "Phase 1 — Desktop home-server hardware, Ubuntu, and network foundation" not in master_plan
    )
    assert "install Ubuntu Server 24.04.4 LTS headless" not in master_plan
    assert "operating_system: ubuntu_server_24_04_4_lts" not in master_plan
    assert "Q9[Qwen 3.5 9B]" not in master_plan
    assert "OLL --> Q9" not in master_plan
    assert "Fast model before main model" not in master_plan
    assert "Main model only when complexity requires it" not in master_plan
    assert "Ubuntu Server installation and hardening" not in status_content
    assert "The 128 GB SSD initially hosts Ubuntu" not in master_plan
    assert "Ubuntu Server, Docker, PostgreSQL, pgvector" not in master_plan
    assert "fast/main selection rules" not in master_plan
