from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import WebSocket

from personal_ai_os.identity.contracts import DevicePrincipal
from personal_ai_os.satellites.windows.connection import SatelliteConnectionManager
from personal_ai_os.satellites.windows.contracts import (
    CommandObservationFrame,
    ToolCommand,
)
from personal_ai_os.satellites.windows.errors import DuplicateSatelliteSessionError
from personal_ai_os.tools.contracts import (
    AvailabilityState,
    RiskLevel,
    SandboxPolicy,
    ToolExecutionRequest,
    ToolObservationStatus,
)
from personal_ai_os.tools.registry import argument_digest, default_registry


class _Socket:
    def __init__(self) -> None:
        self.sent: asyncio.Queue[str] = asyncio.Queue()

    async def send_text(self, value: str) -> None:
        await self.sent.put(value)


def _principal() -> DevicePrincipal:
    return DevicePrincipal(
        owner_id=uuid4(),
        device_id=uuid4(),
        credential_id=uuid4(),
        scopes=frozenset({"satellite.connect", "tool.request"}),
    )


def _request(principal: DevicePrincipal) -> ToolExecutionRequest:
    arguments = {"root_id": "documents", "query": "report", "max_results": 5}
    return ToolExecutionRequest(
        tool_call_id=uuid4(),
        name="windows.files.search",
        version=1,
        owner_id=principal.owner_id,
        device_id=uuid4(),
        arguments=arguments,
        argument_digest=argument_digest(arguments),
        execution_target="windows_satellite_executor",
        required_device_capabilities=frozenset({"windows.files.search"}),
        risk_level=RiskLevel.READ,
        sandbox_policy=SandboxPolicy.SATELLITE_TYPED,
        timeout_seconds=2,
        deadline_at=datetime.now(UTC) + timedelta(seconds=5),
        correlation_id="phase09-transport-test",
    )


def test_dispatch_binds_observation_and_duplicate_session_fails() -> None:
    async def scenario() -> None:
        manager = SatelliteConnectionManager()
        socket = _Socket()
        principal = _principal()
        session_id = uuid4()
        manager.register(
            principal,
            cast(WebSocket, socket),
            session_id,
            frozenset({"windows.files.search"}),
        )
        descriptor = default_registry().resolve("windows.files.search", 1)
        assert manager.availability(descriptor, principal) is AvailabilityState.AVAILABLE
        with pytest.raises(DuplicateSatelliteSessionError):
            manager.register(
                principal,
                cast(WebSocket, _Socket()),
                uuid4(),
                frozenset({"windows.files.search"}),
            )

        request = _request(principal)
        pending = asyncio.create_task(manager.dispatch(request))
        sent = ToolCommand.model_validate_json(await socket.sent.get(), strict=True)
        assert sent.arguments == request.arguments
        assert sent.argument_digest == request.argument_digest
        manager.accept_observation(
            principal.device_id,
            session_id,
            CommandObservationFrame(
                session_id=session_id,
                command_id=sent.command_id,
                name=sent.name,
                version=sent.version,
                argument_digest=sent.argument_digest,
                status=ToolObservationStatus.SUCCEEDED,
                output={"root_id": "documents", "results": [], "truncated": False},
                verification={"verified": True, "root_containment": True},
                observed_at=datetime.now(UTC),
            ),
        )
        assert (await pending).status is ToolObservationStatus.SUCCEEDED
        manager.unregister(principal.device_id, session_id)
        assert manager.availability(descriptor, principal) is AvailabilityState.OFFLINE

    asyncio.run(scenario())


def test_cancel_frame_targets_only_the_bound_command() -> None:
    async def scenario() -> None:
        manager = SatelliteConnectionManager()
        socket = _Socket()
        principal = _principal()
        session_id = uuid4()
        manager.register(
            principal,
            cast(WebSocket, socket),
            session_id,
            frozenset({"windows.files.search"}),
        )
        request = _request(principal)
        pending = asyncio.create_task(manager.dispatch(request))
        await socket.sent.get()
        assert await manager.request_cancel(request.tool_call_id)
        cancellation = await socket.sent.get()
        assert str(request.tool_call_id) in cancellation
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert not await manager.request_cancel(UUID(int=0))

    asyncio.run(scenario())
