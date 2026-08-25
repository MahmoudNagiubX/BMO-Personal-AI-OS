from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy
import pytest

from personal_ai_os.voice.adapters import OpenWakeWordDetector
from personal_ai_os.voice.contracts import AudioFrame
from personal_ai_os.voice.owner_verifier import (
    OwnerVerifierUnavailable,
    load_owner_verifier_profile,
)


def _profile(tmp_path: Path) -> tuple[Path, Path]:
    profile = tmp_path / "hey_jarvis_owner_verifier"
    profile.mkdir()
    model = tmp_path / "hey_jarvis_v0.1.onnx"
    model.write_bytes(b"official-base-for-test")
    artifact = profile / "verifier.joblib"
    artifact.write_bytes(b"owner-derived-verifier")
    (profile / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "phase-10-hey-jarvis-owner-verifier/v1",
                "wake_phrase": "Hey Jarvis",
                "base_model_name": model.stem,
                "base_model_sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
                "artifact": {
                    "filename": "verifier.joblib",
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                },
                "runtime": "openwakeword==0.6.0; custom_verifier_model",
                "owner_local_only": True,
                "raw_audio_retained": False,
                "validation": {"passed": True},
            }
        ),
        encoding="utf-8",
    )
    return profile, model


def test_owner_profile_validates_base_and_derived_digests(tmp_path: Path) -> None:
    profile_dir, model = _profile(tmp_path)

    profile = load_owner_verifier_profile(
        profile_dir,
        base_model_path=model,
        expected_base_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
    )

    assert profile.custom_verifier_models == {
        "hey_jarvis_v0.1": str(profile_dir / "verifier.joblib")
    }
    assert profile.validation == {"passed": True}


def test_owner_profile_fails_closed_on_artifact_tampering(tmp_path: Path) -> None:
    profile_dir, model = _profile(tmp_path)
    (profile_dir / "verifier.joblib").write_bytes(b"tampered")

    with pytest.raises(OwnerVerifierUnavailable, match="checksum mismatch"):
        load_owner_verifier_profile(
            profile_dir,
            base_model_path=model,
            expected_base_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
        )


def test_owner_profile_rejects_nested_or_external_artifact(tmp_path: Path) -> None:
    profile_dir, model = _profile(tmp_path)
    manifest = json.loads((profile_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["artifact"]["filename"] = "..\\outside.joblib"
    (profile_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(OwnerVerifierUnavailable, match="path is not local"):
        load_owner_verifier_profile(
            profile_dir,
            base_model_path=model,
            expected_base_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
        )


def test_owner_profile_rejects_windows_traversal_on_non_windows_hosts(tmp_path: Path) -> None:
    profile_dir, model = _profile(tmp_path)
    manifest = json.loads((profile_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["artifact"]["filename"] = r"..\outside.joblib"
    (profile_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(OwnerVerifierUnavailable, match="path is not local"):
        load_owner_verifier_profile(
            profile_dir,
            base_model_path=model,
            expected_base_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
        )


def test_openwakeword_receives_only_manifest_verified_custom_verifier(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile_dir, model = _profile(tmp_path)
    calls: list[dict[str, object]] = []

    class FakeModel:
        def __init__(self, **kwargs: object) -> None:
            calls.append(kwargs)

        def predict(self, _samples: object) -> dict[str, float]:
            return {"hey_jarvis_v0.1": 0.9}

    monkeypatch.setattr(
        "personal_ai_os.voice.adapters.importlib.import_module",
        lambda name: SimpleNamespace(Model=FakeModel) if name == "openwakeword.model" else numpy,
    )
    detector = OpenWakeWordDetector(
        model_path=model,
        expected_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
        owner_verifier_profile=profile_dir,
    )

    assert detector.detected(AudioFrame(b"\x00\x00" * 1280)) is True
    assert calls[0]["custom_verifier_models"] == {
        "hey_jarvis_v0.1": str(profile_dir / "verifier.joblib")
    }
    assert calls[0]["custom_verifier_threshold"] == 0.1
