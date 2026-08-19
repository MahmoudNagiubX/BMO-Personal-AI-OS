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


def test_codex_workflow_and_independent_review_rules() -> None:
    agents_content = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "Codex is the default repository implementation specialist" in agents_content
    assert "Independent review is read-only" in agents_content
    assert "sole authority for phase and architecture approval" in agents_content

    workflow_content = (ROOT / "docs/CODEX_WORKFLOW.md").read_text(encoding="utf-8")
    assert "Codex is the default repository implementation specialist" in workflow_content
    assert "Independent review is required before Mahmoud may merge" in workflow_content
    assert "Never merge a pull request" in workflow_content
    assert (
        "Consequential or destructive operations require explicit owner approval"
        in workflow_content
    )


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
    assert "PR #10 merged into `main`" in status
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
    assert "**Superseded by:** ADR-0009" in model_adr
    assert "Qwen3.5 4B as the initial local model" in model_adr


def test_phase_four_active_manifest_and_closeout_docs_exclude_9b() -> None:
    manifest_path = ROOT / "infrastructure/tuf/model_manifest.json"
    manifest = manifest_path.read_text(encoding="utf-8")
    manifest_data = json.loads(manifest)
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
    assert "qwen3.5:9b" not in [model["tag"] for model in manifest_data["models"]]
    assert manifest_data["advanced_llama_cpp"]["model_id"] == "qwen3.5-heretic:9b-q4km"
    assert manifest_data["advanced_llama_cpp"]["endpoint"] == "127.0.0.1:11435"
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
    assert "Phase 1 Lenovo/VENOM repository foundation" in status
    assert "PR #8 merged into `main`" in status
    assert "Lenovo G450 Safety Gate" in status
    assert "Qwen3.5 4B" in phase
    assert "BGE-M3" in phase
    assert "no cloud provider" in " ".join(phase.split())
    assert "PHASE 5A ACCEPTED locally" in report
    assert "Phase 5B and physical deployment have not started" in " ".join(report.split())
    assert 'model_id="qwen3.5:4b"' in registry
    assert 'model_id="bge-m3:567m"' in registry
    assert 'model_id="qwen3.5-heretic:9b-q4km"' in registry
    assert "OPTIONAL_MODELS" in registry


def test_phase_five_b_deployment_acceptance_and_phase_six_boundary() -> None:
    status = (ROOT / "docs/IMPLEMENTATION_STATUS.md").read_text(encoding="utf-8")
    phase = (ROOT / "docs/phases/PHASE_05B_MODEL_GATEWAY_DEPLOYMENT_ACCEPTANCE.md").read_text(
        encoding="utf-8"
    )
    report = (ROOT / "docs/phase_reports/PHASE_05B_REPORT.md").read_text(encoding="utf-8")
    evidence = json.loads(
        (ROOT / "infrastructure/home_server/evidence/phase_05b_model_gateway.json").read_text(
            encoding="utf-8"
        )
    )

    assert "Phase 5B" in phase
    assert "PR #15 merged into `main`" in status
    assert "Phase 6 identity/device enrollment is merged" in status
    assert "Phase 6 was not started" in report
    assert evidence["acceptance"]["phase_6"] == "NOT_STARTED"
    assert evidence["acceptance"]["cloud_fallback"] is False
    assert evidence["transport"]["public_or_lan_11434"] is False


def test_phase_six_identity_boundary_and_phase_seven_stop() -> None:
    status = (ROOT / "docs/IMPLEMENTATION_STATUS.md").read_text(encoding="utf-8")
    phase = (ROOT / "docs/phases/PHASE_06_IDENTITY_DEVICE_ENROLLMENT.md").read_text(
        encoding="utf-8"
    )
    report = (ROOT / "docs/phase_reports/PHASE_06_REPORT.md").read_text(encoding="utf-8")
    evidence = json.loads(
        (ROOT / "infrastructure/home_server/evidence/phase_06_identity_enrollment.json").read_text(
            encoding="utf-8"
        )
    )
    contracts = (ROOT / "src/personal_ai_os/identity/contracts.py").read_text(encoding="utf-8")
    routes = (ROOT / "src/personal_ai_os/api/routes/devices.py").read_text(encoding="utf-8")

    assert "Phase 7 text-first conversation and clients are implemented" in status
    assert "Phase 7 is now separately authorized" in phase
    assert "Phase 6 acceptance, Phase 7 was not started" in report
    assert evidence["phase_7"] == "NOT_STARTED"
    assert evidence["venom_deployment"]["performed"] is False
    assert "device.credential.rotate" in contracts
    assert "/credentials/rotate" in routes
    assert "conversation" not in routes.casefold()


def test_phase_seven_conversation_boundary_is_gateway_only_and_scoped() -> None:
    contracts = (ROOT / "src/personal_ai_os/identity/contracts.py").read_text(encoding="utf-8")
    conversation_code = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src/personal_ai_os/conversations").glob("*.py")
    )
    routes = (ROOT / "src/personal_ai_os/api/routes/conversations.py").read_text(encoding="utf-8")
    client = (ROOT / "scripts/phase_07/text_client.py").read_text(encoding="utf-8")

    for scope in (
        "conversation.read",
        "conversation.write",
        "conversation.stream",
        "conversation.run.cancel",
    ):
        assert scope in contracts
    assert "ModelGateway" in conversation_code
    assert "OllamaProvider" not in conversation_code
    assert "tools=()" in conversation_code
    assert "/events" in routes
    assert "Authorization" in client
    assert "BMO_DEVICE_CREDENTIAL_FILE" in client
    assert "Phase 8" not in conversation_code


def test_phase_eight_tool_authority_has_no_general_command_execution() -> None:
    tool_runtime = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src/personal_ai_os/tools").glob("*.py")
    )
    agent_runtime = (ROOT / "src/personal_ai_os/tools/agent_runtime.py").read_text(encoding="utf-8")
    contracts = (ROOT / "src/personal_ai_os/identity/contracts.py").read_text(encoding="utf-8")
    phase = (ROOT / "docs/phases/PHASE_08_TOOL_PERMISSION_APPROVAL_AUDIT.md").read_text(
        encoding="utf-8"
    )
    threat_model = (ROOT / "docs/security/PHASE_08_THREAT_MODEL.md").read_text(encoding="utf-8")

    for forbidden in ("subprocess", "os.system", "shell=True", "powershell", "/shell"):
        assert forbidden not in tool_runtime.casefold()
    assert "SyntheticToolExecutor" not in agent_runtime
    assert "ToolProposal" in agent_runtime
    assert "tool.catalog.read" in contracts
    assert "scripts/phase_09" not in phase
    assert "Phase 9 implementation" not in phase
    assert "arbitrary host compromise" in threat_model.casefold()


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
    assert "optional text-only Qwen3.5-9B Heretic v2 llama.cpp provider" in status


def test_phase_one_venom_foundation_records_the_limited_owner_waiver() -> None:
    phase = (ROOT / "docs/phases/PHASE_01_LENOVO_CONTROL_PLANE_FOUNDATION.md").read_text(
        encoding="utf-8"
    )
    report = (ROOT / "docs/phase_reports/PHASE_01_LENOVO_FOUNDATION_REPORT.md").read_text(
        encoding="utf-8"
    )
    status = (ROOT / "docs/IMPLEMENTATION_STATUS.md").read_text(encoding="utf-8")
    evidence = (
        ROOT / "infrastructure/home_server/evidence/venom_foundation_handoff.json"
    ).read_text(encoding="utf-8")
    checker = (
        (ROOT / "scripts/phase_01/check_foundation_prerequisites.sh")
        .read_text(encoding="utf-8")
        .casefold()
    )

    master_plan = (ROOT / "docs/MASTER_PLAN.md").read_text(encoding="utf-8")
    adr = (ROOT / "docs/adr/0008-owner-waiver-lenovo-stability-gates.md").read_text(
        encoding="utf-8"
    )

    assert "ACCEPTED_WITH_OWNER_WAIVER" in phase
    assert "ACCEPTED_WITH_OWNER_WAIVER" in report
    assert "physical safety gate" in status.casefold()
    assert "AUTHORIZED_TO_START" in status
    assert "not a stability PASS" in adr
    assert "24-hour then seven-day stability gates" in master_plan
    assert '"status": "incomplete"' in evidence
    assert "~/venom/core/brain" in phase
    assert "not the product backend" in phase
    for forbidden in ("ssh ", "scp ", "rm ", "reboot", "stress", "dd "):
        assert forbidden not in checker


def test_current_venom_physical_gate_evidence_is_not_claimed_complete() -> None:
    evidence = (ROOT / "infrastructure/home_server/evidence/venom_physical_gate.json").read_text(
        encoding="utf-8"
    )
    stability = (
        ROOT / "infrastructure/home_server/evidence/venom_stability_summary.json"
    ).read_text(encoding="utf-8")
    monitor = (ROOT / "scripts/phase_01/venom_stability_monitor.sh").read_text(encoding="utf-8")

    assert '"ethernet_ipv4": "192.162.1.21/24"' in evidence
    assert '"management_lan_risk": "192.162.1.0/24 is not RFC1918' in evidence
    assert '"physical_safety_gate": "WAITING_FOR_24H"' in evidence
    assert '"stability_24h": "WAITING"' in evidence
    assert '"stability_7d": "WAITING"' in evidence
    assert '"phase_5b": "NOT_STARTED"' in evidence
    assert '"status": "OWNER_WAIVER"' in evidence
    assert (
        '"measured_stability": "24h and 7d remain WAITING; '
        'this waiver is not a stability PASS"' in evidence
    )
    assert '"durable_monitoring": true' in evidence
    assert '"status": "PASS"' in evidence
    assert '"recovery_verified": true' in evidence
    assert '"user_timer": "inactive"' in evidence
    assert '"smart_counters"' in evidence
    assert '"persistent_copy_path": "%USERPROFILE%\\\\VENOM-Backups' in evidence
    assert "C:\\\\Users\\\\mahmo" not in evidence
    assert "smart_reallocated_sectors" in monitor
    assert "smart_pending_sectors" in monitor
    assert "smart_offline_uncorrectable_sectors" in monitor
    assert "serial" not in monitor.casefold()
    assert "evaluate_stability_gate.py" in (ROOT / "scripts/verify_governance.py").read_text(
        encoding="utf-8"
    )
    assert '"automatic_pass_claim": false' in stability
    assert "shell history" not in monitor
    assert "private keys" in monitor
