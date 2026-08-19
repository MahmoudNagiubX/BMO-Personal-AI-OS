"""High-entropy enrollment and device credential primitives."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass

_TOKEN_PART = re.compile(r"^[A-Za-z0-9_-]+$")


def hash_secret(value: str) -> str:
    """Hash a high-entropy machine secret for lookup or verification."""

    return hashlib.sha256(value.encode("ascii")).hexdigest()


def generate_enrollment_code() -> str:
    """Generate a URL-safe enrollment code with 192 bits of entropy."""

    return secrets.token_urlsafe(24)


@dataclass(frozen=True, slots=True)
class GeneratedCredential:
    """Raw one-time credential plus persistable non-secret fields."""

    raw: str
    public_id: str
    secret_hash: str


def generate_device_credential() -> GeneratedCredential:
    """Generate an indexed public ID and a 256-bit opaque secret."""

    public_id = secrets.token_urlsafe(12)
    secret = secrets.token_urlsafe(32)
    return GeneratedCredential(
        raw=f"{public_id}.{secret}",
        public_id=public_id,
        secret_hash=hash_secret(secret),
    )


def parse_device_credential(raw: str) -> tuple[str, str] | None:
    """Parse a bounded opaque credential without exposing failure details."""

    if len(raw) > 128 or raw.count(".") != 1:
        return None
    public_id, secret = raw.split(".", maxsplit=1)
    if not (8 <= len(public_id) <= 32 and 32 <= len(secret) <= 64):
        return None
    if _TOKEN_PART.fullmatch(public_id) is None or _TOKEN_PART.fullmatch(secret) is None:
        return None
    return public_id, secret


def verify_secret(secret: str, expected_hash: str) -> bool:
    """Compare a high-entropy secret hash in constant time."""

    return hmac.compare_digest(hash_secret(secret), expected_hash)
