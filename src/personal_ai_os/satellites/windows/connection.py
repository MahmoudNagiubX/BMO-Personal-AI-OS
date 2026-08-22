"""Core-side authenticated Windows satellite connection and executor bridge."""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from uuid import UUID

from fastapi import WebSocket

from personal_ai_os.identity.contracts import DevicePrincipal
from personal_ai_os.satellites.windows.contracts import (
    CancelCommand,
    CommandObservationFrame,
    ToolCommand,
)
from personal_ai_os.satellites.windows.errors import (
    DuplicateSatelliteSessionError,
    SatelliteError,
    SatelliteOfflineError,
    SatelliteProtocolError,
)
from personal_ai_os.tools.contracts import (
    AvailabilityState,
    RiskLevel,
    ToolExecutionRequest,
    ToolObservation,
    ToolObservationStatus,
)
from personal_ai_os.tools.registry import ToolDescriptor

SESSION_FRESHNESS_SECONDS = 45.0


@dataclass(slots=True)
class _PendingCommand:
    name: str
    version: int
    argument_digest: str
    future: asyncio.Future[CommandObservationFrame]


@dataclass(slots=True)
class _ConnectedSatellite:
    principal: DevicePrincipal
    websocket: WebSocket
    session_id: UUID
    capabilities: frozenset[str]
    loop: asyncio.AbstractEventLoop
    last_seen_monotonic: float = field(default_factory=time.monotonic)
    pending: dict[UUID, _PendingCommand] = field(default_factory=dict)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class SatelliteConnectionManager:
    """Track current device sessions and bridge sync tool execution to the ASGI loop."""

    def __init__(self) -> None:
        self._sessions: dict[UUID, _ConnectedSatellite] = {}
        self._lock = RLock()

    def register(
        self,
        principal: DevicePrincipal,
        websocket: WebSocket,
        session_id: UUID,
        capabilities: frozenset[str],
    ) -> None:
        with self._lock:
            existing = self._sessions.get(principal.device_id)
            if existing is not None:
                raise DuplicateSatelliteSessionError("duplicate_satellite_session")
            self._sessions[principal.device_id] = _ConnectedSatellite(
                principal=principal,
                websocket=websocket,
                session_id=session_id,
                capabilities=capabilities,
                loop=asyncio.get_running_loop(),
            )

    def unregister(self, device_id: UUID, session_id: UUID) -> None:
        with self._lock:
            session = self._sessions.get(device_id)
            if session is None or session.session_id != session_id:
                return
            del self._sessions[device_id]
        for pending in tuple(session.pending.values()):
            if not pending.future.done():
                pending.future.set_exception(
                    SatelliteOfflineError("satellite_disconnected_uncertain", uncertain=True)
                )
        session.pending.clear()

    def touch(self, device_id: UUID, session_id: UUID) -> None:
        with self._lock:
            session = self._sessions.get(device_id)
            if session is None or session.session_id != session_id:
                raise SatelliteProtocolError("stale_satellite_session")
            session.last_seen_monotonic = time.monotonic()

    def update_principal(self, principal: DevicePrincipal, session_id: UUID) -> None:
        with self._lock:
            session = self._sessions.get(principal.device_id)
            if session is None or session.session_id != session_id:
                raise SatelliteProtocolError("stale_satellite_session")
            session.principal = principal
            session.last_seen_monotonic = time.monotonic()

    def availability(
        self, descriptor: ToolDescriptor, principal: DevicePrincipal
    ) -> AvailabilityState:
        if descriptor.owner_kind != "windows_satellite":
            return AvailabilityState.AVAILABLE
        matches = self._matching_sessions(
            principal.owner_id, descriptor.required_device_capabilities
        )
        return AvailabilityState.AVAILABLE if len(matches) == 1 else AvailabilityState.OFFLINE

    def connected_count(self, owner_id: UUID, required_capabilities: frozenset[str]) -> int:
        return len(self._matching_sessions(owner_id, required_capabilities))

    def _matching_sessions(
        self, owner_id: UUID, required_capabilities: frozenset[str]
    ) -> list[_ConnectedSatellite]:
        now = time.monotonic()
        with self._lock:
            return [
                session
                for session in self._sessions.values()
                if session.principal.owner_id == owner_id
                and required_capabilities <= session.capabilities
                and now - session.last_seen_monotonic <= SESSION_FRESHNESS_SECONDS
            ]

    def _select_session(self, request: ToolExecutionRequest) -> _ConnectedSatellite:
        matches = self._matching_sessions(request.owner_id, request.required_device_capabilities)
        if len(matches) != 1:
            raise SatelliteOfflineError("satellite_offline")
        return matches[0]

    async def dispatch(self, request: ToolExecutionRequest) -> CommandObservationFrame:
        session = self._select_session(request)
        if len(request.required_device_capabilities) != 1:
            raise SatelliteProtocolError("satellite_capability_binding_invalid")
        future: asyncio.Future[CommandObservationFrame] = session.loop.create_future()
        pending = _PendingCommand(
            name=request.name,
            version=request.version,
            argument_digest=request.argument_digest,
            future=future,
        )
        if request.tool_call_id in session.pending:
            raise SatelliteProtocolError("duplicate_pending_command")
        session.pending[request.tool_call_id] = pending
        command = ToolCommand(
            session_id=session.session_id,
            command_id=request.tool_call_id,
            correlation_id=request.correlation_id,
            name=request.name,
            version=request.version,
            arguments=request.arguments,
            argument_digest=request.argument_digest,
            required_capability=next(iter(request.required_device_capabilities)),
            deadline_at=request.deadline_at,
            timeout_seconds=request.timeout_seconds,
        )
        sent = False
        try:
            async with session.send_lock:
                await session.websocket.send_text(command.model_dump_json())
                sent = True
            return await asyncio.wait_for(future, timeout=request.timeout_seconds + 2.0)
        except TimeoutError as error:
            uncertain = sent and request.risk_level in {
                RiskLevel.CONSEQUENTIAL,
                RiskLevel.CRITICAL,
            }
            code = "satellite_timeout_uncertain" if uncertain else "satellite_timeout"
            raise SatelliteOfflineError(code, uncertain=uncertain) from error
        finally:
            session.pending.pop(request.tool_call_id, None)

    async def request_cancel(self, tool_call_id: UUID) -> bool:
        with self._lock:
            matches = [
                session for session in self._sessions.values() if tool_call_id in session.pending
            ]
        if len(matches) != 1:
            return False
        session = matches[0]
        frame = CancelCommand(
            session_id=session.session_id,
            command_id=tool_call_id,
            sent_at=datetime.now(UTC),
        )
        async with session.send_lock:
            await session.websocket.send_text(frame.model_dump_json())
        return True

    def accept_observation(
        self, device_id: UUID, session_id: UUID, observation: CommandObservationFrame
    ) -> None:
        with self._lock:
            session = self._sessions.get(device_id)
        if session is None or session.session_id != session_id:
            raise SatelliteProtocolError("stale_satellite_session")
        if observation.session_id != session_id:
            raise SatelliteProtocolError("observation_session_mismatch")
        pending = session.pending.get(observation.command_id)
        if pending is None:
            raise SatelliteProtocolError("unknown_observation_command")
        if (
            pending.name != observation.name
            or pending.version != observation.version
            or pending.argument_digest != observation.argument_digest
        ):
            raise SatelliteProtocolError("observation_binding_mismatch")
        session.last_seen_monotonic = time.monotonic()
        if not pending.future.done():
            pending.future.set_result(observation)

    def execute_sync(self, request: ToolExecutionRequest) -> CommandObservationFrame:
        session = self._select_session(request)
        future = asyncio.run_coroutine_threadsafe(self.dispatch(request), session.loop)
        try:
            return future.result(timeout=request.timeout_seconds + 4.0)
        except FutureTimeoutError as error:
            future.cancel()
            uncertain = request.risk_level in {RiskLevel.CONSEQUENTIAL, RiskLevel.CRITICAL}
            raise SatelliteOfflineError(
                "satellite_timeout_uncertain" if uncertain else "satellite_timeout",
                uncertain=uncertain,
            ) from error

    def cancel_sync(self, tool_call_id: UUID) -> bool:
        with self._lock:
            matches = [
                session for session in self._sessions.values() if tool_call_id in session.pending
            ]
        if len(matches) != 1:
            return False
        future = asyncio.run_coroutine_threadsafe(
            self.request_cancel(tool_call_id), matches[0].loop
        )
        try:
            return bool(future.result(timeout=3.0))
        except (FutureTimeoutError, SatelliteError):
            return False


class WindowsSatelliteExecutor:
    """Normalize satellite transport outcomes at the Phase 8 executor boundary."""

    def __init__(self, manager: SatelliteConnectionManager) -> None:
        self.manager = manager

    def execute(self, request: ToolExecutionRequest) -> ToolObservation:
        try:
            frame = self.manager.execute_sync(request)
        except SatelliteError as error:
            return ToolObservation(
                status=ToolObservationStatus.FAILED,
                output={},
                verification={"verified": False, "uncertain_outcome": error.uncertain},
                failure_code=error.code,
            )
        return ToolObservation(
            status=frame.status,
            output=frame.output,
            verification=frame.verification,
            failure_code=frame.failure_code,
            observed_at=frame.observed_at,
        )

    def cancel(self, tool_call_id: UUID) -> bool:
        return self.manager.cancel_sync(tool_call_id)


__all__ = ["SatelliteConnectionManager", "WindowsSatelliteExecutor"]
