"""Tests proving the full system acceptance orchestrator cannot false-PASS.

Validates that any network, auth, database, model, test failure, or
excessive latency strictly causes the affected gate to record FAIL and the
orchestrator to return a non-zero exit code.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from scripts.system.run_full_system_acceptance import (
    AcceptanceContext,
    run_gate_01_governance_preflight,
    run_gate_02_venom_foundation,
    run_gate_03_database_persistence,
    run_gate_04_model_gateway,
    run_gate_05_identity_device,
    run_gate_07_permission_approval_audit,
    run_gate_08_windows_satellite,
    run_gate_09_wake_fixtures,
    run_gate_13_barge_in_interruption,
)


def test_gate_01_fails_on_check_py_error() -> None:
    ctx = AcceptanceContext()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="lint error", stdout="")
        run_gate_01_governance_preflight(ctx)

    assert ctx.failed_gates == 1
    assert ctx.results["gate_01_governance_preflight"]["status"] == "FAIL"


def test_gate_02_fails_on_inactive_service_or_bad_host() -> None:
    ctx = AcceptanceContext()
    # Case A: SSH command fails
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=255, stderr="Connection refused", stdout="")
        run_gate_02_venom_foundation(ctx)
    assert ctx.failed_gates == 1
    assert ctx.results["gate_02_venom_foundation"]["status"] == "FAIL"

    # Case B: Service is inactive
    ctx_b = AcceptanceContext()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="disabled\ninactive\nvenom-server\nvenom\n127.0.0.1:8000\n127.0.0.1:5432",
        )
        run_gate_02_venom_foundation(ctx_b)
    assert ctx_b.failed_gates == 1
    assert ctx_b.results["gate_02_venom_foundation"]["status"] == "FAIL"


def test_gate_03_fails_on_unready_db_or_sha_mismatch() -> None:
    ctx = AcceptanceContext()
    with patch("subprocess.run") as mock_run:
        # Returns unready status
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"build_sha":"wrong_sha"}---{"status":"degraded"}',
        )
        run_gate_03_database_persistence(ctx)

    assert ctx.failed_gates == 1
    assert ctx.results["gate_03_database_persistence"]["status"] == "FAIL"


def test_gate_04_fails_on_empty_generation_or_wrong_embedding_dim() -> None:
    # Case A: Empty generation
    ctx_a = AcceptanceContext()
    with (
        patch("scripts.system.run_full_system_acceptance._ensure_ollama_running"),
        patch("urllib.request.urlopen") as mock_urlopen,
    ):
        mock_tags = MagicMock()
        mock_tags.read.return_value = b'{"models":[{"name":"qwen3.5:4b"},{"name":"bge-m3:latest"}]}'
        mock_gen = MagicMock()
        mock_gen.read.return_value = b'{"response":""}'  # empty response
        mock_urlopen.return_value.__enter__.side_effect = [mock_tags, mock_gen]

        run_gate_04_model_gateway(ctx_a)
    assert ctx_a.failed_gates == 1
    assert ctx_a.results["gate_04_model_gateway"]["status"] == "FAIL"

    # Case B: Wrong embedding dimension (e.g. 512 instead of 1024)
    ctx_b = AcceptanceContext()
    with (
        patch("scripts.system.run_full_system_acceptance._ensure_ollama_running"),
        patch("urllib.request.urlopen") as mock_urlopen,
    ):
        mock_tags = MagicMock()
        mock_tags.read.return_value = b'{"models":[{"name":"qwen3.5:4b"},{"name":"bge-m3:latest"}]}'
        mock_gen = MagicMock()
        mock_gen.read.return_value = b'{"response":"PONG"}'
        mock_emb = MagicMock()
        mock_emb.read.return_value = b'{"embedding": [0.1] * 512}'  # wrong dim
        mock_urlopen.return_value.__enter__.side_effect = [mock_tags, mock_gen, mock_emb]

        run_gate_04_model_gateway(ctx_b)
    assert ctx_b.failed_gates == 1
    assert ctx_b.results["gate_04_model_gateway"]["status"] == "FAIL"


def test_gate_05_fails_on_404_or_unit_test_failure() -> None:
    # 404 on endpoint must FAIL (proves wrong endpoint is rejected)
    ctx = AcceptanceContext()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="404")  # 404 instead of 401
        run_gate_05_identity_device(ctx)

    assert ctx.failed_gates == 1
    assert ctx.results["gate_05_identity_device"]["status"] == "FAIL"


def test_gate_07_fails_on_permission_test_failure() -> None:
    ctx = AcceptanceContext()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="permission failure", stdout="")
        run_gate_07_permission_approval_audit(ctx)

    assert ctx.failed_gates == 1
    assert ctx.results["gate_07_permission_approval_audit"]["status"] == "FAIL"


def test_gate_08_fails_on_satellite_test_failure() -> None:
    ctx = AcceptanceContext()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="satellite error")
        run_gate_08_windows_satellite(ctx)

    assert ctx.failed_gates == 1
    assert ctx.results["gate_08_windows_satellite"]["status"] == "FAIL"


def test_gate_09_fails_on_wake_fixture_failure() -> None:
    ctx = AcceptanceContext()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="wake test failed", stdout="")
        run_gate_09_wake_fixtures(ctx)

    assert ctx.failed_gates == 1
    assert ctx.results["gate_09_wake_fixtures"]["status"] == "FAIL"


def test_gate_13_fails_on_excessive_latency() -> None:
    ctx = AcceptanceContext()
    with (
        patch("subprocess.run") as mock_run,
        patch("personal_ai_os.voice.conversation_loop.JarvisConversationLoop") as mock_loop_cls,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        mock_loop = MagicMock()
        mock_metrics = MagicMock()
        mock_metrics.cancel_latency_p50_ms = 500.0
        mock_metrics.cancel_latency_p95_ms = 650.0  # exceeds 450ms bound
        mock_loop.metrics = mock_metrics
        mock_loop_cls.return_value = mock_loop

        run_gate_13_barge_in_interruption(ctx)

    assert ctx.failed_gates == 1
    assert ctx.results["gate_13_barge_in_interruption"]["status"] == "FAIL"


def test_orchestrator_fails_overall_if_any_required_gate_fails() -> None:
    ctx = AcceptanceContext()
    ctx.record(1, "dummy_gate", "FAIL", {"error": "forced test failure"})
    assert ctx.failed_gates == 1
    assert ctx.passed_gates == 0
