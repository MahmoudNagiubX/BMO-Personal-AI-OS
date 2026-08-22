"""Strict schemas for the Phase 9 Windows satellite tool catalog."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr

from personal_ai_os.identity.contracts import StrictContract

StableId = StrictStr


class WindowsStatusArguments(StrictContract):
    pass


class BatteryMetrics(StrictContract):
    present: StrictBool
    percent: StrictFloat | None = Field(default=None, ge=0, le=100)
    on_ac_power: StrictBool | None = None


class GpuMetrics(StrictContract):
    available: StrictBool
    utilization_percent: StrictFloat | None = Field(default=None, ge=0, le=100)
    memory_used_bytes: StrictInt | None = Field(default=None, ge=0)
    memory_total_bytes: StrictInt | None = Field(default=None, ge=0)
    temperature_c: StrictFloat | None = Field(default=None, ge=-20, le=120)


class WindowsStatusOutput(StrictContract):
    timestamp_utc: datetime
    cpu_percent: StrictFloat = Field(ge=0, le=100)
    memory_percent: StrictFloat = Field(ge=0, le=100)
    memory_available_bytes: StrictInt = Field(ge=0)
    disk_percent: StrictFloat = Field(ge=0, le=100)
    disk_free_bytes: StrictInt = Field(ge=0)
    network_bytes_sent: StrictInt = Field(ge=0)
    network_bytes_received: StrictInt = Field(ge=0)
    battery: BatteryMetrics
    gpu: GpuMetrics


class FileSearchArguments(StrictContract):
    root_id: StableId = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9._-]*$")
    query: StrictStr = Field(min_length=1, max_length=100)
    max_results: StrictInt = Field(default=20, ge=1, le=50)


class FileMetadata(StrictContract):
    relative_path: StrictStr = Field(min_length=1, max_length=500)
    name: StrictStr = Field(min_length=1, max_length=255)
    size_bytes: StrictInt = Field(ge=0)
    modified_at: datetime


class FileSearchOutput(StrictContract):
    root_id: StableId
    results: list[FileMetadata] = Field(max_length=50)
    truncated: StrictBool


class AppOpenArguments(StrictContract):
    app_id: StableId = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9._-]*$")


class AppOpenOutput(StrictContract):
    app_id: StableId
    dispatched: Literal[True]
    process_observed: StrictBool


class ProjectOpenArguments(StrictContract):
    project_id: StableId = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9._-]*$")


class ProjectOpenOutput(StrictContract):
    project_id: StableId
    dispatched: Literal[True]
    target_verified: Literal[True]


class VolumeGetArguments(StrictContract):
    pass


class VolumeGetOutput(StrictContract):
    volume: StrictInt = Field(ge=0, le=100)


class VolumeSetArguments(StrictContract):
    volume: StrictInt = Field(ge=0, le=100)


class VolumeSetOutput(StrictContract):
    requested_volume: StrictInt = Field(ge=0, le=100)
    measured_volume: StrictInt = Field(ge=0, le=100)


class WorkflowArguments(StrictContract):
    workflow_id: StableId = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9._-]*$")


class WorkflowOutput(StrictContract):
    workflow_id: StableId
    exit_code: StrictInt
    verification_passed: Literal[True]


__all__ = [
    "AppOpenArguments",
    "AppOpenOutput",
    "FileSearchArguments",
    "FileSearchOutput",
    "ProjectOpenArguments",
    "ProjectOpenOutput",
    "VolumeGetArguments",
    "VolumeGetOutput",
    "VolumeSetArguments",
    "VolumeSetOutput",
    "WindowsStatusArguments",
    "WindowsStatusOutput",
    "WorkflowArguments",
    "WorkflowOutput",
]
