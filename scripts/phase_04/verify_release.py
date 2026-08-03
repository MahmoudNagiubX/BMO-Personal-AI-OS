"""Verify the pinned official Ollama Windows release before execution."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import posixpath
import re
import shutil
import stat
import subprocess
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any, cast

EXPECTED_ASSET = "ollama-windows-amd64.zip"
EXPECTED_CHECKSUMS = "sha256sum.txt"
EXPECTED_RELEASE = "v0.32.5"
EXPECTED_VERSION = "0.32.5"
EXPECTED_COMMIT_PREFIX = "eec8e0b"
GITHUB_RELEASE_URL = "https://api.github.com/repos/ollama/ollama/releases/tags/v0.32.5"
GITHUB_TAG_REF_URL = "https://api.github.com/repos/ollama/ollama/git/ref/tags/v0.32.5"
OFFICIAL_DOWNLOAD_PREFIX = "https://github.com/ollama/ollama/releases/download/v0.32.5/"


class VerificationError(RuntimeError):
    """Raised when a release or runtime artifact fails a required gate."""


def parse_sha256sum(contents: str, asset_name: str = EXPECTED_ASSET) -> str:
    """Return the hexadecimal checksum for an exact asset name."""

    matches: list[str] = []
    for raw_line in contents.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) >= 2 and fields[1].lstrip("*") == asset_name:
            candidate = fields[0].lower()
            if re.fullmatch(r"[0-9a-f]{64}", candidate):
                matches.append(candidate)
            else:
                raise VerificationError(f"Invalid checksum for {asset_name}")
    if len(matches) != 1:
        raise VerificationError(f"Expected exactly one checksum for {asset_name}")
    return matches[0]


def sha256_file(path: Path) -> str:
    """Hash a file without loading it into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hashes_equal(expected: str, actual: str) -> bool:
    """Compare hexadecimal hashes without early-exit comparison."""

    return hmac.compare_digest(expected.lower(), actual.lower())


def require_digest_prefix(digest: str, expected_prefix: str) -> str:
    """Validate and return an Ollama-style full SHA-256 digest."""

    normalized = digest.removeprefix("sha256:").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise VerificationError("Model digest is not a full SHA-256 digest")
    if not hmac.compare_digest(normalized[: len(expected_prefix)], expected_prefix.lower()):
        raise VerificationError("Model digest does not match the locked prefix")
    return f"sha256:{normalized}"


def _normalized_zip_member(name: str) -> str:
    normalized = name.replace("\\", "/")
    if not normalized or "\x00" in normalized:
        raise VerificationError("ZIP member contains an invalid name")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise VerificationError("ZIP member has an absolute path")
    parts = PurePosixPath(normalized).parts
    if any(part == ".." for part in parts):
        raise VerificationError("ZIP member contains path traversal")
    if any(":" in part for part in parts):
        raise VerificationError("ZIP member contains alternate-stream syntax")
    collapsed = posixpath.normpath(normalized)
    if collapsed in ("", ".") or collapsed.startswith("../"):
        raise VerificationError("ZIP member normalizes outside the archive root")
    return collapsed.casefold()


def validate_zip_members(members: Iterable[zipfile.ZipInfo | str]) -> tuple[str, ...]:
    """Reject traversal, alternate streams, symlinks, and duplicate paths."""

    normalized_names: list[str] = []
    seen: set[str] = set()
    for member in members:
        if isinstance(member, zipfile.ZipInfo):
            name = member.filename
            mode = (member.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:
                raise VerificationError("ZIP member is a symbolic link")
        else:
            name = member
        normalized = _normalized_zip_member(name)
        if normalized in seen:
            raise VerificationError("ZIP contains duplicate normalized paths")
        seen.add(normalized)
        normalized_names.append(normalized)
    return tuple(normalized_names)


def safe_extract(zip_path: Path, destination: Path) -> Path:
    """Validate all members, then extract an archive into an empty directory."""

    if destination.exists() and any(destination.iterdir()):
        raise VerificationError("Runtime destination must be empty before extraction")
    destination.mkdir(parents=True, exist_ok=True)
    destination_resolved = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        validate_zip_members(archive.infolist())
        for member in archive.infolist():
            target = (destination / member.filename.replace("\\", "/")).resolve()
            if target != destination_resolved and destination_resolved not in target.parents:
                raise VerificationError("ZIP extraction target escapes destination")
        archive.extractall(destination)
    return find_ollama_executable(destination)


def find_ollama_executable(root: Path) -> Path:
    """Find exactly one non-symlink Ollama executable below a runtime root."""

    candidates: list[Path] = []
    for path in root.rglob("ollama.exe"):
        if path.is_file() and not path.is_symlink():
            candidates.append(path)
    if len(candidates) != 1:
        raise VerificationError("Expected exactly one ollama.exe in the runtime tree")
    return candidates[0].resolve()


def validate_release_metadata(payload: Mapping[str, Any]) -> dict[str, str]:
    """Validate release identity and return only official asset URLs."""

    if payload.get("tag_name") != EXPECTED_RELEASE:
        raise VerificationError("Release tag is not v0.32.5")
    if payload.get("draft") or payload.get("prerelease") or payload.get("withdrawn"):
        raise VerificationError("Release is draft, prerelease, or withdrawn")
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise VerificationError("Release assets are missing")

    urls: dict[str, str] = {}
    for asset in assets:
        if not isinstance(asset, Mapping):
            continue
        name = asset.get("name")
        url = asset.get("browser_download_url")
        if name in (EXPECTED_ASSET, EXPECTED_CHECKSUMS) and isinstance(url, str):
            if not url.startswith(OFFICIAL_DOWNLOAD_PREFIX):
                raise VerificationError("Release asset URL is not the official Ollama URL")
            urls[str(name)] = url
    if set(urls) != {EXPECTED_ASSET, EXPECTED_CHECKSUMS}:
        raise VerificationError("Required official release assets are missing")
    return urls


def require_release_commit(commit_sha: str, expected_prefix: str = EXPECTED_COMMIT_PREFIX) -> str:
    """Validate the official release tag's resolved commit identity."""

    normalized = commit_sha.lower().removeprefix("0x")
    if not re.fullmatch(r"[0-9a-f]{40}", normalized):
        raise VerificationError("Release commit is not a full Git SHA")
    if not hmac.compare_digest(normalized[: len(expected_prefix)], expected_prefix.lower()):
        raise VerificationError("Release commit does not match the locked prefix")
    return normalized


def validate_model_manifest(payload: Mapping[str, Any], allow_pending: bool = True) -> None:
    """Validate the stable model manifest shape without contacting Ollama."""

    if payload.get("schema_version") != 1 or payload.get("ollama_version") != EXPECTED_VERSION:
        raise VerificationError("Unsupported model manifest version")
    runtime = payload.get("runtime")
    if not isinstance(runtime, Mapping) or runtime.get("version") != EXPECTED_VERSION:
        raise VerificationError("Runtime manifest is missing the pinned Ollama version")
    executable_sha = runtime.get("executable_sha256")
    if executable_sha not in (None, ""):
        if not isinstance(executable_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", executable_sha):
            raise VerificationError("Runtime executable hash is invalid")
    elif not allow_pending:
        raise VerificationError("Runtime executable hash is still pending")
    models = payload.get("models")
    if not isinstance(models, list):
        raise VerificationError("Model manifest entries are missing")
    roles: set[str] = set()
    for model in models:
        if not isinstance(model, Mapping):
            raise VerificationError("Model manifest entry is not an object")
        role = model.get("role")
        tag = model.get("tag")
        digest = model.get("digest")
        if not isinstance(role, str) or role in roles:
            raise VerificationError("Model roles must be unique strings")
        if not isinstance(tag, str) or not tag or ":" not in tag:
            raise VerificationError("Model tag is invalid")
        if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            if allow_pending and digest in (None, ""):
                roles.add(role)
                continue
            raise VerificationError("Model digest is not a full SHA-256 digest")
        size_value = model.get("size_bytes")
        if (not isinstance(size_value, int) or size_value <= 0) and not (
            allow_pending and size_value in (None, 0)
        ):
            raise VerificationError("Model size must be a positive integer")
        roles.add(role)


def _fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "BMO-Phase-04-Release-Verifier",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            parsed = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise VerificationError("Official release metadata could not be retrieved") from exc
    if not isinstance(parsed, dict):
        raise VerificationError("Official release metadata is not an object")
    return cast(dict[str, Any], parsed)


def _download(url: str, target: Path) -> None:
    if not url.startswith(OFFICIAL_DOWNLOAD_PREFIX):
        raise VerificationError("Refusing a non-official download URL")
    if os.name == "nt":
        curl = shutil.which("curl.exe")
        if curl is None:
            raise VerificationError("Windows curl.exe is required for the official asset download")
        completed = subprocess.run(
            [
                curl,
                "--fail",
                "--location",
                "--silent",
                "--show-error",
                "--retry",
                "3",
                "--retry-delay",
                "2",
                "--connect-timeout",
                "30",
                "--max-time",
                "1800",
                "--output",
                str(target),
                url,
            ],
            capture_output=True,
            text=True,
            timeout=1810,
            check=False,
        )
        if completed.returncode != 0:
            target.unlink(missing_ok=True)
            raise VerificationError("Official release asset could not be downloaded")
        return
    request = urllib.request.Request(url, headers={"User-Agent": "BMO-Phase-04-Release-Verifier"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
    except (OSError, urllib.error.URLError) as exc:
        target.unlink(missing_ok=True)
        raise VerificationError("Official release asset could not be downloaded") from exc


def get_authenticode(path: Path) -> dict[str, str]:
    """Collect Authenticode status when running on Windows."""

    if os.name != "nt":
        return {"status": "unavailable", "signer": "unavailable", "thumbprint": "unavailable"}
    escaped = str(path).replace("'", "''")
    command = (
        "$signature = Get-AuthenticodeSignature -LiteralPath '"
        + escaped
        + "'; [pscustomobject]@{status=$signature.Status; "
        + "signer=$signature.SignerCertificate.Subject; "
        + "thumbprint=$signature.SignerCertificate.Thumbprint} | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        return {"status": "unavailable", "signer": "unavailable", "thumbprint": "unavailable"}
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"status": "unavailable", "signer": "unavailable", "thumbprint": "unavailable"}
    if not isinstance(result, Mapping):
        return {"status": "unavailable", "signer": "unavailable", "thumbprint": "unavailable"}
    return {
        "status": str(result.get("status") or "Unknown"),
        "signer": str(result.get("signer") or ""),
        "thumbprint": str(result.get("thumbprint") or ""),
    }


def verify_extracted_runtime(executable: Path) -> dict[str, Any]:
    """Hash and version-check an already safely extracted executable."""

    if executable.name.casefold() != "ollama.exe" or not executable.is_file():
        raise VerificationError("Expected ollama.exe is missing")
    completed = subprocess.run(
        [str(executable), "--version"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    if completed.returncode != 0 or not re.search(rf"\b{re.escape(EXPECTED_VERSION)}\b", output):
        raise VerificationError("Ollama executable did not report version 0.32.5")
    return {
        "version": EXPECTED_VERSION,
        "executable_sha256": sha256_file(executable),
        "authenticode": get_authenticode(executable),
    }


def verify_release(
    download_dir: Path,
    runtime_root: Path,
    output_path: Path,
    release_api_url: str = GITHUB_RELEASE_URL,
    tag_commit_sha: str | None = None,
) -> dict[str, Any]:
    """Download, verify, extract, and record the official runtime release."""

    metadata = _fetch_json(release_api_url)
    asset_urls = validate_release_metadata(metadata)
    if tag_commit_sha is None:
        tag_payload = _fetch_json(GITHUB_TAG_REF_URL)
        tag_object = tag_payload.get("object")
        if not isinstance(tag_object, Mapping) or not isinstance(tag_object.get("sha"), str):
            raise VerificationError("Release tag commit identity is missing")
        tag_commit_sha = str(tag_object["sha"])
    release_commit = require_release_commit(tag_commit_sha)

    download_dir.mkdir(parents=True, exist_ok=True)
    archive_path = download_dir / EXPECTED_ASSET
    checksum_path = download_dir / EXPECTED_CHECKSUMS
    _download(asset_urls[EXPECTED_ASSET], archive_path)
    _download(asset_urls[EXPECTED_CHECKSUMS], checksum_path)
    expected_archive_sha = parse_sha256sum(checksum_path.read_text(encoding="utf-8"))
    actual_archive_sha = sha256_file(archive_path)
    if not hashes_equal(expected_archive_sha, actual_archive_sha):
        raise VerificationError("Ollama archive SHA-256 does not match the official checksum")

    executable = safe_extract(archive_path, runtime_root)
    runtime = verify_extracted_runtime(executable)
    record: dict[str, Any] = {
        "release_tag": EXPECTED_RELEASE,
        "release_commit": release_commit,
        "asset": EXPECTED_ASSET,
        "archive_sha256": actual_archive_sha,
        "executable_relative_path": str(executable.relative_to(runtime_root)).replace("\\", "/"),
        **runtime,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-api-url", default=GITHUB_RELEASE_URL)
    parser.add_argument("--tag-commit-sha")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    try:
        record = verify_release(
            download_dir=args.download_dir,
            runtime_root=args.runtime_root,
            output_path=args.output,
            release_api_url=args.release_api_url,
            tag_commit_sha=args.tag_commit_sha,
        )
    except VerificationError as exc:
        raise SystemExit(f"Phase 4 release verification failed: {exc}") from exc
    print(json.dumps({"status": "verified", "release_tag": record["release_tag"]}))


if __name__ == "__main__":
    main()
