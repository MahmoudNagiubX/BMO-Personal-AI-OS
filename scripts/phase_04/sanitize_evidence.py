"""Sanitize and validate the deterministic Phase 4 evidence document."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast


class EvidenceSanitizationError(ValueError):
    """Raised when evidence contains data outside the committed allowlist."""


ALLOWED_TOP_LEVEL_KEYS = {
    "phase",
    "schema_version",
    "collected_utc",
    "hardware",
    "ollama",
    "models",
    "functional",
    "embeddings",
    "thermals",
    "restart",
    "security",
    "acceptance",
    "limitations",
}
FORBIDDEN_KEY_PARTS = {
    "api_key",
    "command_line",
    "cookie",
    "credential",
    "environment",
    "hostname",
    "mac_address",
    "password",
    "path",
    "personal",
    "prompt",
    "raw",
    "response",
    "serial",
    "token",
    "username",
}
RAW_FIELD_PATTERN = re.compile(r"(?:^|_)raw(?:_|$)")
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
    re.compile(r"\b(?:gh[pousr]_|sk-|AIza)[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\b(?:api[_ -]?key|password|secret|token)\s*[:=]"),
    re.compile(r"(?i)\bserial(?:number)?\s*[:=]"),
    re.compile(r"(?i)[A-Z]:\\Users\\"),
    re.compile(r"(?i)\\Users\\[^\\]+\\"),
    re.compile(r"(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b"),
)
IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _check_string(value: str) -> None:
    for pattern in SECRET_PATTERNS:
        if pattern.search(value):
            raise EvidenceSanitizationError("Evidence contains a forbidden sensitive value")
    try:
        candidate = ipaddress.ip_address(value)
    except ValueError:
        for match in IPV4_PATTERN.finditer(value):
            try:
                embedded = ipaddress.ip_address(match.group(0))
            except ValueError:
                continue
            if not embedded.is_loopback:
                raise EvidenceSanitizationError(
                    "Evidence contains a non-loopback IP address"
                ) from None
    else:
        if not candidate.is_loopback:
            raise EvidenceSanitizationError("Evidence contains a non-loopback IP address")


def _walk(value: Any, key: str = "") -> None:
    key_lower = key.casefold()
    if key and (
        any(part != "raw" and part in key_lower for part in FORBIDDEN_KEY_PARTS)
        or RAW_FIELD_PATTERN.search(key_lower)
    ):
        raise EvidenceSanitizationError("Evidence contains a forbidden field")
    if isinstance(value, str):
        _check_string(value)
    elif isinstance(value, Mapping):
        for child_key, child_value in value.items():
            if not isinstance(child_key, str):
                raise EvidenceSanitizationError("Evidence keys must be strings")
            _walk(child_value, child_key)
    elif isinstance(value, list):
        for item in value:
            _walk(item, key)
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise EvidenceSanitizationError("Evidence contains an unsupported value type")


def sanitize_document(document: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a stable JSON-compatible evidence document."""

    unknown = set(document) - ALLOWED_TOP_LEVEL_KEYS
    if unknown:
        raise EvidenceSanitizationError("Evidence contains an unknown top-level field")
    required = {"phase", "schema_version", "ollama", "models", "security", "acceptance"}
    if not required.issubset(document):
        raise EvidenceSanitizationError("Evidence is missing a required top-level field")
    _walk(document)
    return cast(dict[str, Any], json.loads(json.dumps(document, sort_keys=True)))


def write_sanitized(document: Mapping[str, Any], output: Path) -> None:
    """Write a deterministic sanitized JSON document."""

    sanitized = sanitize_document(document)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(sanitized, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--restart-json", type=Path)
    parser.add_argument("--replace", action="store_true")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    if args.output.exists() and args.output.resolve() != args.input.resolve() and not args.replace:
        raise SystemExit("Refusing to overwrite evidence without --replace")
    document = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise SystemExit("Evidence input must be a JSON object")
    merged = dict(document)
    if args.restart_json:
        restart = json.loads(args.restart_json.read_text(encoding="utf-8"))
        if not isinstance(restart, Mapping):
            raise SystemExit("Restart evidence must be a JSON object")
        merged["restart"] = dict(restart)
    try:
        write_sanitized(merged, args.output)
    except (OSError, json.JSONDecodeError, EvidenceSanitizationError) as exc:
        raise SystemExit(f"Evidence sanitization failed: {exc}") from exc
    print("Phase 4 evidence sanitization passed.")


if __name__ == "__main__":
    main()
