from __future__ import annotations

from unittest.mock import MagicMock, patch

from personal_ai_os.voice.tunnel import (
    DEFAULT_VENOM_HOST,
    classify_ssh_error,
    configured_venom_host,
    probe_core_health,
    sanitize_ssh_output,
)


def test_sanitize_ssh_output_strips_user_paths_and_tokens() -> None:
    raw = (
        "Failed to load key C:\\Users\\mahmo\\.ssh\\venom_ed25519 with Bearer eyJhbGciOiJIUzI1NiJ9"
    )
    sanitized = sanitize_ssh_output(raw)

    assert "mahmo" not in sanitized
    assert "C:\\Users" not in sanitized
    assert "<path>" in sanitized
    assert "eyJhbGci" not in sanitized
    assert "<token>" in sanitized


def test_classify_ssh_error_permission_denied() -> None:
    category, message = classify_ssh_error(255, "Permission denied (publickey).")

    assert category == "SSH_AUTH_FAILED"
    assert "rejected" in message


def test_classify_ssh_error_host_key_failed() -> None:
    category, message = classify_ssh_error(255, "Host key verification failed.")

    assert category == "SSH_HOST_KEY_FAILED"
    assert "host key" in message


def test_classify_ssh_error_host_unreachable() -> None:
    category, message = classify_ssh_error(
        255, "ssh: connect to host 192.162.1.28 port 22: Connection timed out"
    )

    assert category == "SSH_HOST_UNREACHABLE"
    assert "unreachable" in message
    assert DEFAULT_VENOM_HOST in message


def test_configured_venom_host_defaults_to_current_host(monkeypatch: object) -> None:
    monkeypatch.delenv("BMO_VENOM_HOST", raising=False)

    assert configured_venom_host() == "192.162.1.28"


def test_configured_venom_host_accepts_safe_override(monkeypatch: object) -> None:
    monkeypatch.setenv("BMO_VENOM_HOST", "venom-server.local")

    assert configured_venom_host() == "venom-server.local"


def test_configured_venom_host_rejects_shell_and_url_values(monkeypatch: object) -> None:
    monkeypatch.setenv("BMO_VENOM_HOST", "192.162.1.28;bad")

    assert configured_venom_host() == DEFAULT_VENOM_HOST


def test_classify_ssh_error_uses_explicit_safe_host() -> None:
    category, message = classify_ssh_error(
        255,
        "Connection timed out",
        venom_host="venom-server.local",
    )

    assert category == "SSH_HOST_UNREACHABLE"
    assert "venom-server.local" in message


def test_classify_ssh_error_port_conflict() -> None:
    category, message = classify_ssh_error(255, "bind [127.0.0.1]:18000: Address already in use")

    assert category == "LOCAL_PORT_CONFLICT"
    assert "bound" in message


def test_classify_ssh_error_forward_failed() -> None:
    category, message = classify_ssh_error(
        255, "channel 1: open failed: connect failed: forwarding failed"
    )

    assert category == "SSH_FORWARD_FAILED"
    assert "forwarding" in message


def test_classify_ssh_error_timeout() -> None:
    category, message = classify_ssh_error(0, "")

    assert category == "SSH_TIMEOUT"
    assert "deadline" in message


def test_probe_core_health_returns_true_on_200() -> None:
    mock_conn = MagicMock()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_conn.getresponse.return_value = mock_response

    with patch("http.client.HTTPConnection", return_value=mock_conn):
        assert probe_core_health("http://127.0.0.1:18000") is True


def test_probe_core_health_returns_false_on_connection_failure() -> None:
    mock_conn = MagicMock()
    mock_conn.request.side_effect = OSError("Connection refused")

    with patch("http.client.HTTPConnection", return_value=mock_conn):
        assert probe_core_health("http://127.0.0.1:18000") is False
