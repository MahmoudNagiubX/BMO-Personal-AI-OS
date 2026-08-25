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
    "docs/phases/PHASE_01_LENOVO_CONTROL_PLANE_FOUNDATION.md",
    "docs/phases/PHASE_04_TUF_MODEL_NODE.md",
    "docs/phases/PHASE_05A_MODEL_GATEWAY.md",
    "docs/phases/PHASE_05B_MODEL_GATEWAY_DEPLOYMENT_ACCEPTANCE.md",
    "docs/phases/PHASE_06_IDENTITY_DEVICE_ENROLLMENT.md",
    "docs/phases/PHASE_07_TEXT_FIRST_CONVERSATION_CLIENTS.md",
    "docs/phases/PHASE_08_TOOL_PERMISSION_APPROVAL_AUDIT.md",
    "docs/phases/PHASE_10_JARVIS_VOICE_CORE.md",
    "docs/phases/PHASE_11_ROOM_MULTI_DEVICE_VOICE.md",
    "docs/adr/ADR_TEMPLATE.md",
    "docs/adr/0001-architecture-baseline.md",
    "docs/adr/0002-openjarvis-adapter.md",
    "docs/adr/0003-compute-control-split.md",
    "docs/adr/0004-repository-license.md",
    "docs/adr/0005-desktop-server-control-plane.md",
    "docs/adr/0006-initial-model-stack.md",
    "docs/adr/0007-restore-lenovo-temporary-control-plane.md",
    "docs/adr/0008-owner-waiver-lenovo-stability-gates.md",
    "docs/adr/0009-llama-cpp-advanced-provider.md",
    "docs/adr/0010-jarvis-voice-core-and-room-voice-boundary.md",
    "docs/adr/0011-jarvis-voice-architecture-v2.md",
    "docs/legal/LICENSE_INVENTORY.md",
    "docs/legal/THIRD_PARTY_NOTICES.md",
    "docs/phase_reports/PHASE_04_REPORT.md",
    "docs/phase_reports/PHASE_05A_REPORT.md",
    "docs/phase_reports/PHASE_05B_REPORT.md",
    "docs/phase_reports/PHASE_06_REPORT.md",
    "docs/phase_reports/PHASE_07_REPORT.md",
    "docs/phase_reports/PHASE_08_REPORT.md",
    "docs/phase_reports/PHASE_08_5_REPORT.md",
    "docs/phase_reports/PHASE_10_REPORT.md",
    "docs/phase_reports/PHASE_01_LENOVO_FOUNDATION_REPORT.md",
    "infrastructure/home_server/README.md",
    "infrastructure/home_server/evidence/venom_foundation_handoff.json",
    "infrastructure/home_server/evidence/venom_physical_gate.json",
    "infrastructure/home_server/evidence/venom_stability_summary.json",
    "infrastructure/home_server/evidence/phase_05b_model_gateway.json",
    "infrastructure/home_server/evidence/phase_06_identity_enrollment.json",
    "infrastructure/home_server/evidence/phase_07_text_conversation.json",
    "infrastructure/home_server/evidence/phase_08_tool_permission_approval_audit.json",
    "infrastructure/home_server/runbooks/01-foundation-inventory.md",
    "infrastructure/home_server/runbooks/02-ssh-firewall.md",
    "infrastructure/home_server/runbooks/03-logs-backup-restore.md",
    "infrastructure/home_server/runbooks/04-reboot-and-stability.md",
    "infrastructure/tuf/model_manifest.json",
    "infrastructure/tuf/advanced/start_phase_08_5_llama_cpp.ps1",
    "infrastructure/tuf/advanced/stop_phase_08_5_llama_cpp.ps1",
    "docs/phase_reports/evidence/PHASE_08_5_LLAMA_CPP.json",
    "docs/phase_reports/evidence/PHASE_10_JARVIS_VOICE_CORE.json",
    "docs/phase_reports/evidence/PHASE_10_JARVIS_VOICE_V2.json",
    "docs/phase_reports/evidence/PHASE_10_JARVIS_WAKE_MODEL.json",
    "docs/phase_reports/evidence/PHASE_10_HEY_JARVIS_MODEL.json",
    "docs/phase_reports/evidence/PHASE_10_HEY_JARVIS_FINAL.json",
    "scripts/phase_01/check_foundation_prerequisites.sh",
    "scripts/phase_01/validate_foundation_evidence.py",
    "scripts/phase_01/validate_physical_gate_evidence.py",
    "scripts/phase_01/evaluate_stability_gate.py",
    "scripts/phase_01/venom_bounded_memory_gate.sh",
    "scripts/phase_01/venom_bounded_thermal_gate.sh",
    "scripts/phase_01/venom_prepare_config_backup.sh",
    "scripts/phase_01/venom_pre_reboot_check.sh",
    "scripts/phase_01/venom_privileged_closeout.sh",
    "scripts/phase_01/venom_restore_config_backup.sh",
    "scripts/phase_01/venom_start_official_gate.sh",
    "scripts/phase_01/venom_start_new_official_gate.sh",
    "scripts/phase_01/venom_stability_monitor.sh",
    "scripts/phase_06/bootstrap_owner.py",
    "scripts/phase_06/create_enrollment.py",
    "scripts/phase_06/list_devices.py",
    "scripts/phase_06/revoke_device.py",
    "scripts/phase_06/validate_evidence.py",
    "scripts/phase_07/text_client.py",
    "scripts/phase_07/validate_evidence.py",
    "scripts/phase_08/validate_evidence.py",
    "scripts/phase_08_5/validate_evidence.py",
    "scripts/phase_10/validate_evidence.py",
    "scripts/phase_10/validate_wake_model_manifest.py",
    "infrastructure/home_server/systemd/venom-phase1-stability.service",
    "infrastructure/home_server/systemd/venom-phase1-stability.timer",
    "infrastructure/home_server/systemd/venom-phase1-stability-user.service",
    "infrastructure/home_server/systemd/venom-phase1-stability-user.timer",
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
            "OpenJarvis",
            "Qwen 3.5 4B",
            "Lenovo G450",
            "Ubuntu Server 24.04.4 LTS",
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
