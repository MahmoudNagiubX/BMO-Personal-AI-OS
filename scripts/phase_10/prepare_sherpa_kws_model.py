"""Prepare the official sherpa-onnx open-vocabulary ``Jarvis`` model locally.

Only the pinned official release is accepted.  The archive, model files, and
generated keyword manifest stay outside Git; no microphone or test audio is
copied into the prepared runtime directory.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from personal_ai_os.voice.adapters import (
    SHERPA_ONNX_KWS_ARCHIVE_SHA256,
    SHERPA_ONNX_KWS_ARTIFACT,
)

ARCHIVE_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/"
    f"{SHERPA_ONNX_KWS_ARTIFACT}.tar.bz2"
)
REQUIRED_FILES = (
    "bpe.model",
    "tokens.txt",
    "encoder-epoch-12-avg-2-chunk-16-left-64.onnx",
    "decoder-epoch-12-avg-2-chunk-16-left-64.onnx",
    "joiner-epoch-12-avg-2-chunk-16-left-64.onnx",
    "README.md",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest(output: Path) -> dict[str, Any]:
    manifest_path = output / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("prepared sherpa-onnx KWS manifest is missing")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("prepared sherpa-onnx KWS manifest is invalid")
    if payload.get("archive_sha256") != SHERPA_ONNX_KWS_ARCHIVE_SHA256:
        raise ValueError("prepared sherpa-onnx KWS archive identity is not accepted")
    files = payload.get("files")
    if not isinstance(files, dict):
        raise ValueError("prepared sherpa-onnx KWS file hashes are missing")
    for name, expected in files.items():
        path = output / str(name)
        if not path.is_file() or _sha256(path) != expected:
            raise ValueError(f"prepared sherpa-onnx KWS verification failed: {name}")
    return payload


def prepare(output: Path, archive: Path | None = None) -> dict[str, Any]:
    """Download/prepare one verified model directory without retaining audio."""

    if (output / "manifest.json").is_file():
        return _manifest(output)
    if any(output.iterdir()) if output.exists() else False:
        raise ValueError("refusing to overwrite a non-empty unverified model directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bmo-sherpa-kws-") as temporary:
        temp_root = Path(temporary)
        archive_path = archive
        if archive_path is None:
            archive_path = temp_root / f"{SHERPA_ONNX_KWS_ARTIFACT}.tar.bz2"
            urllib.request.urlretrieve(ARCHIVE_URL, archive_path)
        if _sha256(archive_path) != SHERPA_ONNX_KWS_ARCHIVE_SHA256:
            raise ValueError("official sherpa-onnx KWS archive SHA-256 mismatch")
        with tarfile.open(archive_path, mode="r:bz2") as bundle:
            bundle.extractall(temp_root, filter="data")
        source = temp_root / SHERPA_ONNX_KWS_ARTIFACT
        if not source.is_dir():
            raise ValueError("official sherpa-onnx KWS archive layout is invalid")
        output.mkdir()
        for name in REQUIRED_FILES:
            shutil.copy2(source / name, output / name)
        try:
            sherpa_onnx = importlib.import_module("sherpa_onnx")
        except ImportError as exc:
            raise RuntimeError("sherpa-onnx is required for official keyword generation") from exc
        encoded = sherpa_onnx.text2token(
            ["JARVIS"],
            str(output / "tokens.txt"),
            tokens_type="bpe",
            bpe_model=str(output / "bpe.model"),
        )
        if len(encoded) != 1 or not encoded[0]:
            raise ValueError("official keyword generation returned no Jarvis tokens")
        (output / "keywords.txt").write_text(
            " ".join(str(token) for token in encoded[0]) + "\n",
            encoding="utf-8",
        )
        files = {name: _sha256(output / name) for name in (*REQUIRED_FILES, "keywords.txt")}
        manifest: dict[str, Any] = {
            "schema_version": "phase-10-sherpa-onnx-kws/v1",
            "artifact": SHERPA_ONNX_KWS_ARTIFACT,
            "source_url": ARCHIVE_URL,
            "archive_sha256": SHERPA_ONNX_KWS_ARCHIVE_SHA256,
            "wake_word": "Jarvis",
            "keyword_file": "keywords.txt",
            "keyword_line_count": 1,
            "keyword_generation": "sherpa_onnx.text2token(tokens_type=bpe)",
            "license": "Apache-2.0",
            "files": files,
            "raw_audio_retained": False,
        }
        (output / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return _manifest(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    payload = prepare(args.output, args.archive)
    print(
        json.dumps(
            {
                "status": "SHERPA_ONNX_KWS_PREPARED",
                "artifact": payload["artifact"],
                "archive_sha256": payload["archive_sha256"],
                "wake_word": payload["wake_word"],
                "keyword_line_count": payload["keyword_line_count"],
                "raw_audio_retained": payload["raw_audio_retained"],
                "file_count": len(payload["files"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
