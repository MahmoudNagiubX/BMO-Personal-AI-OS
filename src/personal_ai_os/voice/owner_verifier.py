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
from pathlib import Path, PureWindowsPath
from typing import Any, cast

from personal_ai_os.voice.wake_phrase import PRIMARY_WAKE_PHRASE
from personal_ai_os.voice.wake_policy import WakePolicyMode

OWNER_VERIFIER_SCHEMA = "phase-10-hey-jarvis-owner-verifier/v2"
OWNER_VERIFIER_ARTIFACT = "verifier.joblib"
OWNER_VERIFIER_MANIFEST = "manifest.json"


class OwnerVerifierUnavailable(RuntimeError):
    """Raised when the owner-local verifier cannot be trusted or loaded."""


@dataclass(frozen=True, slots=True)
class OwnerVerifierWakeContract:
    """The manifest-bound separation between candidate and final decisions."""

    base_candidate_invoke_threshold: float
    final_owner_verifier_accept_threshold: float | None
    temporal_policy: WakePolicyMode
    temporal_window_frames: int
    required_hits_in_window: int
    deactivation_threshold: float
    openwakeword_vad_threshold: float | None


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
    wake_contract: OwnerVerifierWakeContract
    production_ready: bool

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
    windows_relative = PureWindowsPath(relative_name)
    if (
        relative.is_absolute()
        or windows_relative.is_absolute()
        or windows_relative.drive
        or "/" in relative_name
        or "\\" in relative_name
        or relative.name != relative_name
        or len(relative.parts) != 1
    ):
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


def _required_probability(value: Any, field: str, *, allow_none: bool = False) -> float | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, (float, int)) or isinstance(value, bool) or not 0.0 <= value <= 1.0:
        raise OwnerVerifierUnavailable(f"owner wake verifier manifest field is invalid: {field}")
    return float(value)


def _wake_contract(manifest: dict[str, Any]) -> OwnerVerifierWakeContract:
    contract = manifest.get("wake_contract")
    if not isinstance(contract, dict):
        raise OwnerVerifierUnavailable("owner wake verifier threshold contract is missing")
    base_threshold = _required_probability(
        contract.get("base_candidate_invoke_threshold"), "base_candidate_invoke_threshold"
    )
    base_status = _required_text(
        contract.get("base_candidate_threshold_status"), "base_candidate_threshold_status"
    )
    if base_status not in {
        "calibrated_broad_synthetic",
        "provisional_pending_broad_synthetic_calibration",
    }:
        raise OwnerVerifierUnavailable("owner wake verifier base threshold status is invalid")
    if base_threshold is None:
        raise AssertionError("required base threshold unexpectedly missing")
    final_threshold = _required_probability(
        contract.get("final_owner_verifier_accept_threshold"),
        "final_owner_verifier_accept_threshold",
        allow_none=True,
    )
    temporal_policy = _required_text(contract.get("temporal_policy"), "temporal_policy")
    if temporal_policy not in {"threshold_crossing", "moving_average", "moving_max"}:
        raise OwnerVerifierUnavailable("owner wake verifier temporal policy is invalid")
    window = contract.get("temporal_window_frames")
    hits = contract.get("required_hits_in_window")
    if (
        not isinstance(window, int)
        or isinstance(window, bool)
        or not 1 <= window <= 5
        or not isinstance(hits, int)
        or isinstance(hits, bool)
        or not 1 <= hits <= window
    ):
        raise OwnerVerifierUnavailable("owner wake verifier temporal bounds are invalid")
    deactivation = _required_probability(
        contract.get("deactivation_threshold"), "deactivation_threshold"
    )
    if deactivation is None:
        raise AssertionError("required deactivation threshold unexpectedly missing")
    vad = _required_probability(
        contract.get("openwakeword_vad_threshold"),
        "openwakeword_vad_threshold",
        allow_none=True,
    )
    return OwnerVerifierWakeContract(
        base_candidate_invoke_threshold=float(base_threshold),
        final_owner_verifier_accept_threshold=final_threshold,
        temporal_policy=cast(WakePolicyMode, temporal_policy),
        temporal_window_frames=window,
        required_hits_in_window=hits,
        deactivation_threshold=float(deactivation),
        openwakeword_vad_threshold=vad,
    )


def load_owner_verifier_profile(
    profile_dir: Path,
    *,
    base_model_path: Path,
    expected_base_sha256: str,
    expected_phrase: str = PRIMARY_WAKE_PHRASE,
    require_production_ready: bool = True,
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
    wake_contract = _wake_contract(manifest)
    production_ready = manifest.get("production_ready")
    if not isinstance(production_ready, bool):
        raise OwnerVerifierUnavailable("owner wake verifier production readiness is invalid")
    if require_production_ready and not production_ready:
        raise OwnerVerifierUnavailable("owner wake verifier profile is provisional")
    if require_production_ready and manifest["wake_contract"].get(
        "base_candidate_threshold_status"
    ) != ("calibrated_broad_synthetic"):
        raise OwnerVerifierUnavailable(
            "owner wake verifier base threshold is not broadly calibrated"
        )
    if production_ready and wake_contract.final_owner_verifier_accept_threshold is None:
        raise OwnerVerifierUnavailable("production owner wake verifier threshold is missing")
    if wake_contract.openwakeword_vad_threshold is not None:
        raise OwnerVerifierUnavailable(
            "owner wake verifier internal VAD is not production-approved"
        )

    return OwnerVerifierProfile(
        profile_dir=profile_dir,
        artifact_path=artifact_path,
        model_name=model_name,
        wake_phrase=expected_phrase,
        base_model_sha256=actual_base_sha256,
        artifact_sha256=actual_artifact_sha256,
        validation=validation,
        wake_contract=wake_contract,
        production_ready=production_ready,
    )


__all__ = [
    "OWNER_VERIFIER_ARTIFACT",
    "OWNER_VERIFIER_MANIFEST",
    "OWNER_VERIFIER_SCHEMA",
    "OwnerVerifierProfile",
    "OwnerVerifierUnavailable",
    "OwnerVerifierWakeContract",
    "default_owner_verifier_dir",
    "load_owner_verifier_profile",
    "sha256_file",
]
