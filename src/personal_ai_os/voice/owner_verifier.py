"""Safe lifecycle and manifest handling for the owner-local wake verifier.

The verifier itself is produced by the pinned openWakeWord training API.  It
is intentionally kept outside Git because it is derived from the owner's
voice.  This module validates the local manifest and both artifact digests
before the upstream runtime is allowed to load its scikit-learn object.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from personal_ai_os.voice.wake_phrase import PRIMARY_WAKE_PHRASE

OWNER_VERIFIER_SCHEMA = "phase-10-hey-jarvis-owner-verifier/v1"
OWNER_VERIFIER_ARTIFACT = "verifier.joblib"
OWNER_VERIFIER_MANIFEST = "manifest.json"


class OwnerVerifierUnavailable(RuntimeError):
    """Raised when the owner-local verifier cannot be trusted or loaded."""


@dataclass(frozen=True, slots=True)
class OwnerVerifierProfile:
    """Validated local profile metadata passed to openWakeWord."""

    profile_dir: Path
    artifact_path: Path
    model_name: str
    wake_phrase: str
    base_model_sha256: str
    artifact_sha256: str
    validation: dict[str, Any]

    @property
    def custom_verifier_models(self) -> dict[str, str]:
        """Return the exact mapping expected by openWakeWord.Model."""

        return {self.model_name: str(self.artifact_path)}


def sha256_file(path: Path) -> str:
    """Hash a file in bounded blocks without retaining its contents."""

    digest = hashlib.sha256()
    try:
        digest.update(path.read_bytes())
    except OSError as exc:
        raise OwnerVerifierUnavailable("owner wake verifier artifact is unreadable") from exc
    return digest.hexdigest()


def default_owner_verifier_dir() -> Path:
    """Return the approved owner-local profile location."""

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise OwnerVerifierUnavailable("LOCALAPPDATA is required for the owner wake profile")
    return Path(local_app_data) / "BMO" / "voice" / "wake" / "hey_jarvis_owner_verifier"


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OwnerVerifierUnavailable("owner wake verifier manifest is unreadable") from exc
    if not isinstance(value, dict):
        raise OwnerVerifierUnavailable("owner wake verifier manifest must be an object")
    return value


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise OwnerVerifierUnavailable(f"owner wake verifier manifest field is invalid: {field}")
    return value


def _safe_child(profile_dir: Path, relative_name: str, field: str) -> Path:
    relative = Path(relative_name)
    if relative.is_absolute() or relative.name != relative_name or len(relative.parts) != 1:
        raise OwnerVerifierUnavailable(f"owner wake verifier {field} path is not local")
    candidate = profile_dir / relative
    if candidate.is_symlink():
        raise OwnerVerifierUnavailable(f"owner wake verifier {field} must not be a symlink")
    try:
        if candidate.resolve().parent != profile_dir.resolve():
            raise OwnerVerifierUnavailable(f"owner wake verifier {field} escapes its profile")
    except OSError as exc:
        raise OwnerVerifierUnavailable(f"owner wake verifier {field} path is unreadable") from exc
    return candidate


def load_owner_verifier_profile(
    profile_dir: Path,
    *,
    base_model_path: Path,
    expected_base_sha256: str,
    expected_phrase: str = PRIMARY_WAKE_PHRASE,
) -> OwnerVerifierProfile:
    """Validate a local profile before allowing upstream pickle loading."""

    if not profile_dir.is_dir() or profile_dir.is_symlink():
        raise OwnerVerifierUnavailable("owner wake verifier profile is missing")
    model_path = base_model_path
    if not model_path.is_file() or model_path.is_symlink():
        raise OwnerVerifierUnavailable("owner wake verifier base model is missing")
    actual_base_sha256 = sha256_file(model_path)
    if actual_base_sha256.casefold() != expected_base_sha256.casefold():
        raise OwnerVerifierUnavailable("owner wake verifier base model checksum mismatch")

    manifest = _read_object(profile_dir / OWNER_VERIFIER_MANIFEST)
    if manifest.get("schema_version") != OWNER_VERIFIER_SCHEMA:
        raise OwnerVerifierUnavailable("owner wake verifier manifest schema is unsupported")
    if _required_text(manifest.get("wake_phrase"), "wake_phrase") != expected_phrase:
        raise OwnerVerifierUnavailable("owner wake verifier phrase does not match production")
    model_name = _required_text(manifest.get("base_model_name"), "base_model_name")
    if model_name != model_path.stem:
        raise OwnerVerifierUnavailable("owner wake verifier base model name mismatch")
    if _required_text(manifest.get("base_model_sha256"), "base_model_sha256").casefold() != (
        actual_base_sha256.casefold()
    ):
        raise OwnerVerifierUnavailable("owner wake verifier manifest base checksum mismatch")
    if (
        manifest.get("owner_local_only") is not True
        or manifest.get("raw_audio_retained") is not False
    ):
        raise OwnerVerifierUnavailable("owner wake verifier privacy contract is invalid")
    if manifest.get("runtime") != "openwakeword==0.6.0; custom_verifier_model":
        raise OwnerVerifierUnavailable("owner wake verifier runtime identity is invalid")

    artifact = manifest.get("artifact")
    if not isinstance(artifact, dict):
        raise OwnerVerifierUnavailable("owner wake verifier artifact metadata is missing")
    artifact_name = _required_text(artifact.get("filename"), "artifact.filename")
    artifact_path = _safe_child(profile_dir, artifact_name, "artifact")
    if artifact_name != OWNER_VERIFIER_ARTIFACT or not artifact_path.is_file():
        raise OwnerVerifierUnavailable("owner wake verifier artifact is missing")
    expected_artifact_sha256 = _required_text(artifact.get("sha256"), "artifact.sha256")
    actual_artifact_sha256 = sha256_file(artifact_path)
    if actual_artifact_sha256.casefold() != expected_artifact_sha256.casefold():
        raise OwnerVerifierUnavailable("owner wake verifier artifact checksum mismatch")
    validation = manifest.get("validation")
    if not isinstance(validation, dict):
        raise OwnerVerifierUnavailable("owner wake verifier validation metadata is missing")

    return OwnerVerifierProfile(
        profile_dir=profile_dir,
        artifact_path=artifact_path,
        model_name=model_name,
        wake_phrase=expected_phrase,
        base_model_sha256=actual_base_sha256,
        artifact_sha256=actual_artifact_sha256,
        validation=validation,
    )


__all__ = [
    "OWNER_VERIFIER_ARTIFACT",
    "OWNER_VERIFIER_MANIFEST",
    "OWNER_VERIFIER_SCHEMA",
    "OwnerVerifierProfile",
    "OwnerVerifierUnavailable",
    "default_owner_verifier_dir",
    "load_owner_verifier_profile",
    "sha256_file",
]
