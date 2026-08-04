from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from scripts.phase_04.verify_release import (
    VerificationError,
    hashes_equal,
    parse_sha256sum,
    release_asset_size,
    require_digest_prefix,
    require_release_commit,
    validate_model_manifest,
    validate_release_metadata,
    validate_runtime_profile,
    validate_zip_members,
)


def test_parse_official_checksum_formats() -> None:
    digest = "a" * 64
    assert parse_sha256sum(f"{digest} *ollama-windows-amd64.zip\n") == digest
    assert parse_sha256sum(f"{digest}  ollama-windows-amd64.zip\n") == digest
    assert parse_sha256sum(f"{digest}  ./ollama-windows-amd64.zip\n") == digest


def test_checksum_requires_one_exact_asset() -> None:
    with pytest.raises(VerificationError):
        parse_sha256sum(f"{'a' * 64} *other.zip\n")
    with pytest.raises(VerificationError):
        parse_sha256sum(
            f"{'a' * 64} *ollama-windows-amd64.zip\n{'b' * 64} *ollama-windows-amd64.zip\n"
        )


def test_hash_comparison_and_digest_prefix_are_strict() -> None:
    assert hashes_equal("AA", "aa")
    assert require_digest_prefix("sha256:" + "a" * 64, "a" * 12) == "sha256:" + "a" * 64
    with pytest.raises(VerificationError):
        require_digest_prefix("sha256:" + "b" * 64, "a" * 12)
    with pytest.raises(VerificationError):
        require_release_commit("a" * 40, "eec8e0b")


def test_zip_members_reject_traversal_absolute_stream_and_duplicates() -> None:
    validate_zip_members(["ollama.exe", "lib/runtime.dll"])
    for unsafe in ("../escape", "/absolute", "C:/absolute", "file:stream"):
        with pytest.raises(VerificationError):
            validate_zip_members([unsafe])
    with pytest.raises(VerificationError):
        validate_zip_members(["bin/../ollama.exe", "ollama.exe"])
    with pytest.raises(VerificationError):
        validate_zip_members(["OLLAMA.EXE", "ollama.exe"])


def test_zip_symlink_is_rejected() -> None:
    info = zipfile.ZipInfo("link")
    info.external_attr = 0o120777 << 16
    with pytest.raises(VerificationError):
        validate_zip_members([info])


def test_release_metadata_requires_official_assets() -> None:
    payload = {
        "tag_name": "v0.32.5",
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": "ollama-windows-amd64.zip",
                "size": 1024,
                "browser_download_url": "https://github.com/ollama/ollama/releases/download/v0.32.5/ollama-windows-amd64.zip",
            },
            {
                "name": "sha256sum.txt",
                "size": 64,
                "browser_download_url": "https://github.com/ollama/ollama/releases/download/v0.32.5/sha256sum.txt",
            },
        ],
    }
    assert set(validate_release_metadata(payload)) == {"ollama-windows-amd64.zip", "sha256sum.txt"}
    assert release_asset_size(payload, "ollama-windows-amd64.zip") == 1024
    payload["assets"][0]["browser_download_url"] = "https://example.invalid/ollama.zip"
    with pytest.raises(VerificationError):
        validate_release_metadata(payload)


def test_model_manifest_pending_and_populated_shapes(tmp_path: Path) -> None:
    profile = {
        "profile": "conservative_cuda",
        "flash_attention": True,
        "kv_cache_type": "q8_0",
        "gpu_overhead_bytes": 536870912,
        "max_parallel_requests": 1,
        "max_loaded_models": 1,
        "keep_alive": "0",
        "listener": "127.0.0.1:11434",
        "cloud_disabled": True,
    }
    pending = {
        "schema_version": 1,
        "ollama_version": "0.32.5",
        "runtime": {"version": "0.32.5", "executable_sha256": None},
        "runtime_profile": profile,
        "models": [],
    }
    validate_model_manifest(pending)
    populated = {
        **pending,
        "runtime": {"version": "0.32.5", "executable_sha256": "a" * 64},
        "models": [
            {
                "role": "fast",
                "tag": "qwen3.5:4b",
                "digest": "sha256:" + "b" * 64,
                "size_bytes": 1,
            }
        ],
    }
    validate_model_manifest(populated, allow_pending=False)


def test_runtime_profile_rejects_unsafe_values() -> None:
    profile = {
        "profile": "conservative_cuda",
        "flash_attention": True,
        "kv_cache_type": "q8_0",
        "gpu_overhead_bytes": 536870912,
        "max_parallel_requests": 1,
        "max_loaded_models": 1,
        "keep_alive": "0",
        "listener": "127.0.0.1:11434",
        "cloud_disabled": True,
    }
    validate_runtime_profile(profile)
    for key, value in (
        ("kv_cache_type", "f16"),
        ("max_parallel_requests", 2),
        ("max_loaded_models", 2),
        ("gpu_overhead_bytes", 0),
        ("listener", "0.0.0.0:11434"),
        ("cloud_disabled", False),
    ):
        unsafe = {**profile, key: value}
        with pytest.raises(VerificationError):
            validate_runtime_profile(unsafe)
