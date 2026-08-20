"""Authenticated outbound-established Windows satellite WebSocket boundary."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, WebSocket
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from personal_ai_os.identity.contracts import DevicePrincipal, HeartbeatRequest
from personal_ai_os.identity.errors import (
    AuthenticationError,
    CapabilityEscalationError,
    ScopeDeniedError,
)
from personal_ai_os.identity.service import IdentityService
from personal_ai_os.satellites.windows.connection import SatelliteConnectionManager
from personal_ai_os.satellites.windows.contracts import (
    HEARTBEAT_INTERVAL_SECONDS,
    MAX_FRAME_BYTES,
    PROTOCOL_VERSION,
    CommandObservationFrame,
    CoreWelcome,
    HeartbeatAck,
    SatelliteHeartbeat,
    SatelliteHello,
    validate_wire_model,
)
from personal_ai_os.satellites.windows.errors import (
    DuplicateSatelliteSessionError,
    SatelliteProtocolError,
)

router = APIRouter(prefix="/api/v1/satellites/windows", tags=["satellites"])


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _credential(websocket: WebSocket) -> str | None:
    value = websocket.headers.get("authorization")
    if value is None:
        return None
    scheme, separator, credential = value.partition(" ")
    if separator != " " or scheme.casefold() != "bearer" or not credential or " " in credential:
        return None
    return credential


async def _receive_object(websocket: WebSocket) -> dict[str, Any]:
    message = await websocket.receive()
    if message.get("type") == "websocket.disconnect":
        raise WebSocketDisconnect(message.get("code", 1000))
    raw = message.get("text")
    if raw is None:
        binary = message.get("bytes")
        if binary is None:
            raise SatelliteProtocolError("satellite_frame_missing")
        if len(binary) > MAX_FRAME_BYTES:
            raise SatelliteProtocolError("satellite_frame_oversize")
        try:
            raw = binary.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SatelliteProtocolError("satellite_frame_invalid") from error
    if len(raw.encode("utf-8")) > MAX_FRAME_BYTES:
        raise SatelliteProtocolError("satellite_frame_oversize")
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except (TypeError, ValueError) as error:
        raise SatelliteProtocolError("satellite_frame_invalid") from error
    if not isinstance(value, dict):
        raise SatelliteProtocolError("satellite_frame_invalid")
    return value


def _authenticate(
    websocket: WebSocket, raw_credential: str
) -> tuple[DevicePrincipal, frozenset[str]]:
    factory = websocket.app.state.database_session_factory
    with factory() as session:
        identity = IdentityService(session)
        principal = identity.authenticate(raw_credential)
        identity.require_scopes(
            principal,
            "satellite.connect",
            "device.heartbeat.write",
            "device.capabilities.report",
        )
        device = identity.device_self(principal)
        if device.device_kind != "windows_satellite" or device.platform != "windows":
            raise ScopeDeniedError("invalid satellite device kind")
        return principal, frozenset(device.approved_capabilities)


def _revalidate(
    websocket: WebSocket,
    principal: DevicePrincipal,
    capabilities: list[str],
    software_version: str,
) -> DevicePrincipal:
    factory = websocket.app.state.database_session_factory
    with factory() as session:
        identity = IdentityService(session)
        refreshed = identity.revalidate_principal(principal)
        identity.require_scopes(
            refreshed,
            "satellite.connect",
            "device.heartbeat.write",
            "device.capabilities.report",
        )
        device = identity.device_self(refreshed)
        if device.device_kind != "windows_satellite" or device.platform != "windows":
            raise ScopeDeniedError("invalid satellite device kind")
        if not set(capabilities).issubset(device.approved_capabilities):
            raise CapabilityEscalationError("capability report exceeds approved inventory")
        identity.heartbeat(
            refreshed,
            HeartbeatRequest(
                software_version=software_version,
                reported_capabilities=capabilities,
            ),
        )
        return refreshed


@router.websocket("/connect")
async def connect_windows_satellite(websocket: WebSocket) -> None:
    """Accept one authenticated Windows device channel established from the TUF."""

    raw_credential = _credential(websocket)
    if raw_credential is None:
        await websocket.close(code=4401, reason="unauthenticated")
        return
    try:
        principal, approved_capabilities = _authenticate(websocket, raw_credential)
    except AuthenticationError:
        await websocket.close(code=4401, reason="unauthenticated")
        return
    except ScopeDeniedError:
        await websocket.close(code=4403, reason="unauthorized")
        return

    await websocket.accept()
    manager: SatelliteConnectionManager = websocket.app.state.satellite_connection_manager
    session_id: UUID | None = None
    try:
        hello_payload = await asyncio.wait_for(_receive_object(websocket), timeout=5.0)
        hello = validate_wire_model(SatelliteHello, hello_payload)
        if hello.protocol_version != PROTOCOL_VERSION:
            raise SatelliteProtocolError("satellite_protocol_version_mismatch")
        if not set(hello.capabilities).issubset(approved_capabilities):
            raise SatelliteProtocolError("satellite_capability_escalation")
        principal = _revalidate(websocket, principal, hello.capabilities, hello.software_version)
        session_id = uuid4()
        manager.register(
            principal,
            websocket,
            session_id,
            frozenset(hello.capabilities),
        )
        await websocket.send_text(CoreWelcome(session_id=session_id).model_dump_json())

        while True:
            payload = await asyncio.wait_for(
                _receive_object(websocket),
                timeout=HEARTBEAT_INTERVAL_SECONDS * 3,
            )
            principal = _revalidate(
                websocket, principal, hello.capabilities, hello.software_version
            )
            manager.update_principal(principal, session_id)
            frame_type = payload.get("type")
            if frame_type == "heartbeat":
                heartbeat = validate_wire_model(SatelliteHeartbeat, payload)
                if heartbeat.session_id != session_id:
                    raise SatelliteProtocolError("stale_satellite_session")
                manager.touch(principal.device_id, session_id)
                await websocket.send_text(
                    HeartbeatAck(
                        session_id=session_id,
                        sequence=heartbeat.sequence,
                        received_at=datetime.now(UTC),
                    ).model_dump_json()
                )
            elif frame_type == "observation":
                observation = validate_wire_model(CommandObservationFrame, payload)
                manager.accept_observation(principal.device_id, session_id, observation)
            else:
                raise SatelliteProtocolError("satellite_frame_type_invalid")
    except DuplicateSatelliteSessionError:
        await websocket.close(code=4409, reason="duplicate session")
    except (ValidationError, SatelliteProtocolError, CapabilityEscalationError):
        await websocket.close(code=4400, reason="invalid satellite frame")
    except AuthenticationError:
        await websocket.close(code=4401, reason="unauthenticated")
    except ScopeDeniedError:
        await websocket.close(code=4403, reason="unauthorized")
    except TimeoutError:
        await websocket.close(code=1011, reason="heartbeat timeout")
    except (RuntimeError, WebSocketDisconnect):
        return
    finally:
        if session_id is not None:
            manager.unregister(principal.device_id, session_id)


__all__ = ["router"]
