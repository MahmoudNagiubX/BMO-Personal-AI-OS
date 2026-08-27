"""VENOM Core loopback tunnel diagnostics and health probe contracts."""

from __future__ import annotations

import http.client
import os
import re
from urllib.parse import urlparse

DEFAULT_VENOM_HOST = "192.162.1.28"
_VENOM_HOST_PATTERN = re.compile(r"^[A-Za-z0-9.-]+$")


def configured_venom_host() -> str:
    """Return the safe current VENOM host used by local diagnostics."""
    configured = os.environ.get("BMO_VENOM_HOST", "").strip()
    if configured and _VENOM_HOST_PATTERN.fullmatch(configured):
        return configured
    return DEFAULT_VENOM_HOST


def sanitize_ssh_output(raw_output: str) -> str:
    """Sanitize SSH stderr by removing user home directories, key paths, and tokens."""
    if not raw_output:
        return ""
    # Strip user paths like C:\Users\<name>\... or /home/<name>/...
    sanitized = re.sub(
        r"(?:[A-Za-z]:)?(?:\/|\\)(?:Users|home)(?:\/|\\)[^\s\:\'\"\,]+",
        "<path>",
        raw_output,
    )
    # Strip bearer tokens or private key fingerprints if any
    sanitized = re.sub(
        r"(?:bearer\s+|token\s+)[A-Za-z0-9_\-\.]+",
        "<token>",
        sanitized,
        flags=re.IGNORECASE,
    )
    return sanitized.strip()


def classify_ssh_error(
    returncode: int,
    raw_stderr: str,
    venom_host: str | None = None,
) -> tuple[str, str]:
    """Classify SSH failure into a truthful, safe category with sanitized message."""
    sanitized = sanitize_ssh_output(raw_stderr)
    lower = raw_stderr.lower()
    display_host = venom_host or configured_venom_host()
    if not _VENOM_HOST_PATTERN.fullmatch(display_host):
        display_host = DEFAULT_VENOM_HOST

    if "permission denied" in lower or "authentication failed" in lower:
        return "SSH_AUTH_FAILED", f"VENOM SSH key authentication rejected by host ({sanitized})"
    if "host key verification failed" in lower:
        return "SSH_HOST_KEY_FAILED", f"VENOM host key verification failed ({sanitized})"
    if any(
        marker in lower
        for marker in (
            "could not resolve hostname",
            "network is unreachable",
            "connection refused",
            "connection timed out",
            "no route to host",
            "operation timed out",
        )
    ):
        return "SSH_HOST_UNREACHABLE", f"VENOM host at {display_host} is unreachable ({sanitized})"
    if "cannot listen to port" in lower or "address already in use" in lower:
        return "LOCAL_PORT_CONFLICT", f"Local port 18000 cannot be bound by SSH ({sanitized})"
    if "forwarding failed" in lower or "remote port forwarding failed" in lower:
        return "SSH_FORWARD_FAILED", f"Port forwarding to VENOM Core failed ({sanitized})"
    if returncode != 0:
        msg = f"SSH tunnel process exited with code {returncode}"
        if sanitized:
            msg += f" ({sanitized})"
        return "SSH_PROCESS_EXITED", msg
    return (
        "SSH_TIMEOUT",
        f"VENOM loopback tunnel did not become ready within deadline ({sanitized})",
    )


def probe_core_health(base_url: str, timeout_seconds: float = 2.0) -> bool:
    """Unauthenticated health probe to verify Core responds over the loopback tunnel."""
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    conn = http.client.HTTPConnection(host, port, timeout=timeout_seconds)
    try:
        conn.request("GET", "/health/live", headers={"User-Agent": "BMO-Voice-Preflight"})
        resp = conn.getresponse()
        return bool(resp.status == 200)
    except (OSError, http.client.HTTPException):
        return False
    finally:
        conn.close()


__all__ = [
    "DEFAULT_VENOM_HOST",
    "classify_ssh_error",
    "configured_venom_host",
    "probe_core_health",
    "sanitize_ssh_output",
]
