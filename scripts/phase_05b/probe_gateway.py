"""Write one sanitized Phase 5B model-gateway health observation."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from personal_ai_os.model_gateway import GatewaySettings, ModelGateway, OllamaProvider
from personal_ai_os.model_gateway.registry import BGE_M3, QWEN_4B


def collect_observation(*, expected_version: str = "0.32.5") -> dict[str, Any]:
    """Collect health scalars without prompts, responses, vectors, or raw provider data."""

    settings = GatewaySettings(
        ollama_endpoint="http://127.0.0.1:11434",
        expected_ollama_version=expected_version,
    )
    health = ModelGateway(OllamaProvider(settings.ollama_endpoint), settings).health()
    presence = {item.model_id: item for item in health.required_models}
    qwen = presence.get(QWEN_4B.model_id)
    bge = presence.get(BGE_M3.model_id)
    return {
        "schema_version": "phase-05b-gateway-observation/v1",
        "timestamp_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "hostname": socket.gethostname(),
        "gateway_availability": health.availability.value,
        "health_reason": health.reason.value,
        "provider_version_match": health.provider_version == "0.32.5",
        "qwen_identity_match": bool(qwen and qwen.present and qwen.identity_matches),
        "bge_identity_match": bool(bge and bge.present and bge.identity_matches),
        "latency_ms": round(health.latency_seconds * 1000, 3),
        "tunnel_listener_present": listener_present(),
    }


def listener_present() -> bool:
    """Return whether the loopback reverse-forward listener accepts a connection."""

    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=0.5):
            return True
    except OSError:
        return False


def write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False, newline="\n"
    ) as stream:
        json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
        temporary = Path(stream.name)
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-version", default="0.32.5")
    args = parser.parse_args()
    payload = collect_observation(expected_version=args.expected_version)
    if args.output:
        write_atomic(args.output, payload)
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    # Offline is an expected capability state. Probe/software failures still exit nonzero.
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"phase_05b_probe_error={type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
