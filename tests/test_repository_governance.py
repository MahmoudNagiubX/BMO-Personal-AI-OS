from __future__ import annotations

import json
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


def test_lenovo_temporary_control_plane_architecture_is_locked() -> None:
    status = (ROOT / "docs/IMPLEMENTATION_STATUS.md").read_text(encoding="utf-8")
    master_plan = (ROOT / "docs/MASTER_PLAN.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    accepted_adr = (ROOT / "docs/adr/0007-restore-lenovo-temporary-control-plane.md").read_text(
        encoding="utf-8"
    )
    superseded_adr = (ROOT / "docs/adr/0005-desktop-server-control-plane.md").read_text(
        encoding="utf-8"
    )
    model_adr = (ROOT / "docs/adr/0006-initial-model-stack.md").read_text(encoding="utf-8")

    assert "Lenovo G450 — temporary lightweight control plane defined by ADR-0007" in master_plan
    assert "Ubuntu Server 24.04.4 LTS AMD64, headless, no GUI" in master_plan
    assert "Core 2 Duo class CPU" in master_plan
    assert "4 GB RAM" in master_plan
    assert "Lenovo G450 Safety Gate" in status
    assert "PR #9 merged and closed" in status
    assert "desktop PC is not the current deployment authority" in status
    assert "Lenovo G450 defined by ADR-0007" in agents
    assert "Ubuntu Server 24.04.4 LTS AMD64, headless with no desktop GUI" in agents
    assert "**Status:** Accepted" in accepted_adr
    assert "**Supersedes:** ADR-0005" in accepted_adr
    assert "future control-plane upgrade or migration candidate" in accepted_adr
    assert "Home Assistant and PostgreSQL/pgvector are admitted only" in accepted_adr
    assert "**Status:** Superseded" in superseded_adr
    assert "**Superseded by:** ADR-0007" in superseded_adr
    assert "Qwen3.5 4B as the initial local model" in model_adr
    assert "Qwen3.5 9B is deferred" in model_adr


def test_phase_four_active_manifest_and_closeout_docs_exclude_9b() -> None:
    manifest_path = ROOT / "infrastructure/tuf/model_manifest.json"
    manifest = manifest_path.read_text(encoding="utf-8")
    phase_spec = (ROOT / "docs/phases/PHASE_04_TUF_MODEL_NODE.md").read_text(encoding="utf-8")
    report = (ROOT / "docs/phase_reports/PHASE_04_REPORT.md").read_text(encoding="utf-8")
    evidence = json.loads(
        (ROOT / "docs/phase_reports/evidence/PHASE_04_TUF_BENCHMARK.json").read_text(
            encoding="utf-8"
        )
    )

    assert [model["role"] for model in json.loads(manifest)["models"]] == [
        "primary",
        "embeddings",
    ]
    assert "qwen3.5:9b" not in manifest
    assert "No model gateway" in phase_spec
    assert "PHASE 4 ACCEPTED locally" in report
    assert "not required" in report
    assert evidence["acceptance"] == "pass"
    assert evidence["restart"]["status"] == "pass"
    assert "committed restart evidence" in report


def test_phase_five_a_gateway_governance_and_next_boundary() -> None:
    status = (ROOT / "docs/IMPLEMENTATION_STATUS.md").read_text(encoding="utf-8")
    phase = (ROOT / "docs/phases/PHASE_05A_MODEL_GATEWAY.md").read_text(encoding="utf-8")
    report = (ROOT / "docs/phase_reports/PHASE_05A_REPORT.md").read_text(encoding="utf-8")
    registry = (ROOT / "src/personal_ai_os/model_gateway/registry.py").read_text(encoding="utf-8")

    assert "PR #9 is merged and Phase 5A is closed" in status
    assert "PR #8 merged into `main`" in status
    assert "Lenovo G450 Safety Gate" in status
    assert "Qwen3.5 4B" in phase
    assert "BGE-M3" in phase
    assert "no cloud provider" in " ".join(phase.split())
    assert "PHASE 5A ACCEPTED locally" in report
    assert "Phase 5B and physical deployment have not started" in " ".join(report.split())
    assert 'model_id="qwen3.5:4b"' in registry
    assert 'model_id="bge-m3:567m"' in registry
    assert "qwen3.5:9b" not in registry.casefold()


def test_historical_lenovo_branch_is_not_reused_for_deployment() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    status = (ROOT / "docs/IMPLEMENTATION_STATUS.md").read_text(encoding="utf-8")
    master_plan = (ROOT / "docs/MASTER_PLAN.md").read_text(encoding="utf-8")

    assert "must not be merged" in readme
    assert "phase-01/lenovo-control-plane-foundation" in status
    assert "must not be merged, rebased, force-pushed, rewritten, or reused" in master_plan


def test_active_architecture_has_no_stale_desktop_or_dual_model_requirements() -> None:
    master_plan = (ROOT / "docs/MASTER_PLAN.md").read_text(encoding="utf-8")
    status = (ROOT / "docs/IMPLEMENTATION_STATUS.md").read_text(encoding="utf-8")

    assert "Phase 1 — Lenovo G450 safety, Ubuntu Server, and network foundation" in master_plan
    assert "operating_system: ubuntu_server_24_04_4_lts" in master_plan
    assert "desktop_pc_upgrade_candidate: true" in master_plan
    assert "lenovo_foundation_reusable: false" in master_plan
    assert "Desktop Home Server Safety Gate" not in status
    assert "Q9[Qwen 3.5 9B]" not in master_plan
    assert "OLL --> Q9" not in master_plan
    assert "main: qwen3.5:9b" not in master_plan
    assert "fast: qwen3.5:4b" not in master_plan
    assert "Qwen3.5 9B remains deferred" in status
