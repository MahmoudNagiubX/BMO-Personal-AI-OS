"""Strict Phase 9 Windows satellite wire contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from personal_ai_os.identity.contracts import CapabilityId, SoftwareVersion, StrictContract
from personal_ai_os.tools.contracts import ToolObservationStatus

PROTOCOL_VERSION: Literal["phase-09-windows-satellite/v1"] = "phase-09-windows-satellite/v1"
MAX_FRAME_BYTES = 16_384
HEARTBEAT_INTERVAL_SECONDS = 15
MAX_IN_FLIGHT_COMMANDS = 2


def validate_wire_model[WireModel: BaseModel](
    model: type[WireModel], payload: dict[str, Any]
) -> WireModel:
    """Validate decoded JSON using JSON scalar semantics and strict contracts."""

    return model.model_validate_json(
        json.dumps(payload, separators=(",", ":")),
        strict=True,
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(UTC)


class SatelliteHello(StrictContract):
    type: Literal["hello"] = "hello"
    protocol_version: Literal["phase-09-windows-satellite/v1"]
    connection_id: UUID
    software_version: SoftwareVersion
    capabilities: list[CapabilityId] = Field(min_length=1, max_length=16)
    sent_at: datetime

    _normalize_sent_at = field_validator("sent_at")(_aware_utc)

    @field_validator("capabilities")
    @classmethod
    def unique_capabilities(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("capabilities must be unique")
        return value


class CoreWelcome(StrictContract):
    type: Literal["welcome"] = "welcome"
    protocol_version: Literal["phase-09-windows-satellite/v1"] = PROTOCOL_VERSION
    session_id: UUID
    heartbeat_interval_seconds: int = HEARTBEAT_INTERVAL_SECONDS
    max_in_flight_commands: int = MAX_IN_FLIGHT_COMMANDS
    max_frame_bytes: int = MAX_FRAME_BYTES


class ToolCommand(StrictContract):
    type: Literal["command"] = "command"
    protocol_version: Literal["phase-09-windows-satellite/v1"] = PROTOCOL_VERSION
    session_id: UUID
    command_id: UUID
    correlation_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1, le=99)
    arguments: dict[str, Any]
    argument_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    required_capability: CapabilityId
    deadline_at: datetime
    timeout_seconds: float = Field(gt=0, le=300)

    _normalize_deadline = field_validator("deadline_at")(_aware_utc)


class CancelCommand(StrictContract):
    type: Literal["cancel"] = "cancel"
    protocol_version: Literal["phase-09-windows-satellite/v1"] = PROTOCOL_VERSION
    session_id: UUID
    command_id: UUID
    sent_at: datetime

    _normalize_sent_at = field_validator("sent_at")(_aware_utc)


class SatelliteHeartbeat(StrictContract):
    type: Literal["heartbeat"] = "heartbeat"
    protocol_version: Literal["phase-09-windows-satellite/v1"] = PROTOCOL_VERSION
    session_id: UUID
    sequence: int = Field(ge=0)
    sent_at: datetime

    _normalize_sent_at = field_validator("sent_at")(_aware_utc)


class HeartbeatAck(StrictContract):
    type: Literal["heartbeat_ack"] = "heartbeat_ack"
    protocol_version: Literal["phase-09-windows-satellite/v1"] = PROTOCOL_VERSION
    session_id: UUID
    sequence: int = Field(ge=0)
    received_at: datetime

    _normalize_received_at = field_validator("received_at")(_aware_utc)


class CommandObservationFrame(StrictContract):
    type: Literal["observation"] = "observation"
    protocol_version: Literal["phase-09-windows-satellite/v1"] = PROTOCOL_VERSION
    session_id: UUID
    command_id: UUID
    name: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1, le=99)
    argument_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: ToolObservationStatus
    output: dict[str, Any]
    verification: dict[str, Any]
    failure_code: str | None = Field(default=None, min_length=1, max_length=96)
    observed_at: datetime

    _normalize_observed_at = field_validator("observed_at")(_aware_utc)


__all__ = [
    "HEARTBEAT_INTERVAL_SECONDS",
    "MAX_FRAME_BYTES",
    "MAX_IN_FLIGHT_COMMANDS",
    "PROTOCOL_VERSION",
    "CancelCommand",
    "CommandObservationFrame",
    "CoreWelcome",
    "HeartbeatAck",
    "SatelliteHeartbeat",
    "SatelliteHello",
    "ToolCommand",
    "validate_wire_model",
]
