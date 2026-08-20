"""Strict owner-managed local Windows satellite allowlist."""

from __future__ import annotations

import json
import os
from pathlib import Path, PureWindowsPath
from typing import Any, Literal

from pydantic import Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from personal_ai_os.identity.contracts import StrictContract

ALLOWLIST_VERSION = "phase-09-windows-allowlist/v1"


def _reject_duplicate_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _fixed_argument(value: str) -> str:
    if not value or len(value) > 500 or "\x00" in value or "\r" in value or "\n" in value:
        raise ValueError("fixed argument is invalid")
    return value


def _canonical_absolute(value: str) -> str:
    if not value or len(value) > 500 or "\x00" in value:
        raise ValueError("path is invalid")
    if any(marker in value for marker in ("%", "$", "~")):
        raise ValueError("path expansion is forbidden")
    if os.name == "nt":
        windows_path = PureWindowsPath(value)
        if not windows_path.is_absolute() or str(windows_path).startswith("\\\\"):
            raise ValueError("path must be an absolute local Windows path")
    else:
        if not Path(value).is_absolute():
            raise ValueError("path must be absolute")
    return str(Path(value).resolve(strict=False))


class _LaunchTarget(StrictContract):
    executable: StrictStr
    fixed_args: list[StrictStr] = Field(default_factory=list, max_length=16)
    working_directory: StrictStr | None = None

    @field_validator("executable")
    @classmethod
    def canonical_executable(cls, value: str) -> str:
        return _canonical_absolute(value)

    @field_validator("working_directory")
    @classmethod
    def canonical_working_directory(cls, value: str | None) -> str | None:
        return None if value is None else _canonical_absolute(value)

    @field_validator("fixed_args")
    @classmethod
    def validate_fixed_args(cls, values: list[str]) -> list[str]:
        return [_fixed_argument(value) for value in values]


class AppEntry(_LaunchTarget):
    app_id: StrictStr = Field(pattern=r"^[a-z][a-z0-9._-]{0,63}$")
    observe_process: StrictBool = True


class ProjectEntry(_LaunchTarget):
    project_id: StrictStr = Field(pattern=r"^[a-z][a-z0-9._-]{0,63}$")
    project_directory: StrictStr

    @field_validator("project_directory")
    @classmethod
    def canonical_project_directory(cls, value: str) -> str:
        return _canonical_absolute(value)


class SearchRootEntry(StrictContract):
    root_id: StrictStr = Field(pattern=r"^[a-z][a-z0-9._-]{0,63}$")
    directory: StrictStr
    max_entries: StrictInt = Field(default=5_000, ge=1, le=20_000)

    @field_validator("directory")
    @classmethod
    def canonical_directory(cls, value: str) -> str:
        return _canonical_absolute(value)


class MarkerVerification(StrictContract):
    kind: Literal["marker_file_exists"]
    path: StrictStr

    @field_validator("path")
    @classmethod
    def canonical_path(cls, value: str) -> str:
        return _canonical_absolute(value)


class WorkflowEntry(_LaunchTarget):
    workflow_id: StrictStr = Field(pattern=r"^[a-z][a-z0-9._-]{0,63}$")
    script: StrictStr
    timeout_seconds: StrictInt = Field(ge=1, le=120)
    expected_exit_codes: list[StrictInt] = Field(min_length=1, max_length=8)
    allow_hard_stop: StrictBool = False
    verification: MarkerVerification

    @field_validator("script")
    @classmethod
    def canonical_script(cls, value: str) -> str:
        return _canonical_absolute(value)

    @field_validator("expected_exit_codes")
    @classmethod
    def unique_exit_codes(cls, values: list[int]) -> list[int]:
        if len(values) != len(set(values)):
            raise ValueError("expected exit codes must be unique")
        return values

    @model_validator(mode="after")
    def validate_interpreter_pair(self) -> WorkflowEntry:
        executable_name = Path(self.executable).name.casefold()
        script_suffix = Path(self.script).suffix.casefold()
        powershell_names = {"powershell.exe", "pwsh.exe", "powershell", "pwsh"}
        if script_suffix == ".ps1" and executable_name not in powershell_names:
            raise ValueError("PowerShell scripts require an exact PowerShell executable")
        if executable_name in powershell_names and script_suffix != ".ps1":
            raise ValueError("PowerShell executable may run only an allowlisted .ps1 script")
        if self.working_directory is None:
            raise ValueError("workflow working_directory is required")
        working_directory = Path(self.working_directory)
        if not Path(self.script).is_relative_to(working_directory):
            raise ValueError("workflow script must remain under its working directory")
        if not Path(self.verification.path).is_relative_to(working_directory):
            raise ValueError("workflow verification must remain under its working directory")
        return self


class AllowlistDocument(StrictContract):
    schema_version: Literal["phase-09-windows-allowlist/v1"]
    apps: list[AppEntry] = Field(default_factory=list, max_length=64)
    projects: list[ProjectEntry] = Field(default_factory=list, max_length=64)
    search_roots: list[SearchRootEntry] = Field(default_factory=list, max_length=32)
    workflows: list[WorkflowEntry] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def reject_duplicate_ids(self) -> AllowlistDocument:
        for entries, attribute in (
            (self.apps, "app_id"),
            (self.projects, "project_id"),
            (self.search_roots, "root_id"),
            (self.workflows, "workflow_id"),
        ):
            values = [getattr(entry, attribute) for entry in entries]
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {attribute}")
        return self


class WindowsAllowlist:
    """Resolved immutable ID maps; network input cannot modify this object."""

    def __init__(self, document: AllowlistDocument) -> None:
        self.apps = {entry.app_id: entry for entry in document.apps}
        self.projects = {entry.project_id: entry for entry in document.projects}
        self.search_roots = {entry.root_id: entry for entry in document.search_roots}
        self.workflows = {entry.workflow_id: entry for entry in document.workflows}

    @classmethod
    def load(cls, path: Path) -> WindowsAllowlist:
        raw = path.read_text(encoding="utf-8")
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_object_pairs)
        return cls(AllowlistDocument.model_validate(value, strict=True))

    def available_capabilities(self) -> frozenset[str]:
        capabilities = {"windows.telemetry.read", "windows.media.control"}
        if any(Path(entry.directory).is_dir() for entry in self.search_roots.values()):
            capabilities.add("windows.files.search")
        if any(Path(entry.executable).is_file() for entry in self.apps.values()):
            capabilities.add("windows.app.open")
        if any(
            Path(entry.executable).is_file() and Path(entry.project_directory).is_dir()
            for entry in self.projects.values()
        ):
            capabilities.add("windows.project.open")
        if any(
            Path(entry.executable).is_file()
            and Path(entry.script).is_file()
            and Path(entry.working_directory or "").is_dir()
            for entry in self.workflows.values()
        ):
            capabilities.add("windows.workflow.start")
        return frozenset(capabilities)


__all__ = [
    "ALLOWLIST_VERSION",
    "AllowlistDocument",
    "WindowsAllowlist",
]
