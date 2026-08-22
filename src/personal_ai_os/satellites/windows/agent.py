"""Per-user outbound Windows satellite agent."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from personal_ai_os.satellites.windows.config import WindowsSatelliteSettings
from personal_ai_os.satellites.windows.contracts import (
    HEARTBEAT_INTERVAL_SECONDS,
    MAX_FRAME_BYTES,
    PROTOCOL_VERSION,
    CancelCommand,
    CommandObservationFrame,
    CoreWelcome,
    HeartbeatAck,
    SatelliteHeartbeat,
    SatelliteHello,
    ToolCommand,
    validate_wire_model,
)
from personal_ai_os.satellites.windows.credentials import CredentialStore
from personal_ai_os.satellites.windows.execution import WindowsExecutionEngine
from personal_ai_os.satellites.windows.replay import ReplayConflictError, ReplayJournal
from personal_ai_os.tools.contracts import ToolObservationStatus


class WindowsSatelliteAgent:
    """Maintain one authenticated outbound channel with bounded reconnect and work."""

    def __init__(
        self,
        settings: WindowsSatelliteSettings,
        credential_store: CredentialStore,
        execution_engine: WindowsExecutionEngine,
        replay_journal: ReplayJournal,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self.settings = settings
        self.credential_store = credential_store
        self.execution_engine = execution_engine
        self.replay_journal = replay_journal
        self.logger = logger or logging.getLogger("bmo.windows_satellite")
        self._stop = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(2)
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._cancel_before_start: set[UUID] = set()

    async def run_forever(self) -> None:
        delay = 1.0
        random_source = random.SystemRandom()
        while not self._stop.is_set():
            credential = self.credential_store.read()
            if credential is None:
                self.logger.warning("satellite credential is unavailable")
            else:
                try:
                    await self._run_connection(credential)
                    delay = 1.0
                except (ConnectionClosed, OSError, TimeoutError, ValidationError, ValueError):
                    self.logger.warning("satellite connection unavailable")
            if self._stop.is_set():
                break
            jitter = random_source.uniform(0.0, min(1.0, delay / 4.0))
            with suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=delay + jitter)
            delay = min(delay * 2.0, self.settings.reconnect_max_seconds)

    async def stop(self) -> None:
        self._stop.set()
        for command_id in tuple(self._tasks):
            self.execution_engine.cancel(command_id)
        if self._tasks:
            await asyncio.wait(tuple(self._tasks.values()), timeout=5.0)

    async def _run_connection(self, credential: str) -> None:
        capabilities = sorted(self.execution_engine.available_capabilities())
        if not capabilities:
            raise ValueError("satellite has no available capabilities")
        async with connect(
            self.settings.endpoint,
            additional_headers={"Authorization": f"Bearer {credential}"},
            max_size=MAX_FRAME_BYTES,
            open_timeout=10,
            close_timeout=5,
            ping_interval=None,
        ) as websocket:
            hello = SatelliteHello(
                protocol_version=PROTOCOL_VERSION,
                connection_id=uuid4(),
                software_version=self.settings.software_version,
                capabilities=capabilities,
                sent_at=datetime.now(UTC),
            )
            await websocket.send(hello.model_dump_json())
            welcome = validate_wire_model(
                CoreWelcome,
                self._decode(await asyncio.wait_for(websocket.recv(), timeout=5.0)),
            )
            if welcome.protocol_version != PROTOCOL_VERSION:
                raise ValueError("satellite protocol mismatch")
            heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(websocket, welcome.session_id)
            )
            self.logger.info("satellite session connected")
            try:
                async for raw in websocket:
                    payload = self._decode(raw)
                    frame_type = payload.get("type")
                    if frame_type == "command":
                        command = validate_wire_model(ToolCommand, payload)
                        if command.session_id != welcome.session_id:
                            raise ValueError("stale satellite session")
                        if len(self._tasks) >= welcome.max_in_flight_commands:
                            await self._send_observation(
                                websocket,
                                self._failure(command, "satellite_busy"),
                            )
                            continue
                        task = asyncio.create_task(self._handle_command(websocket, command))
                        self._tasks[command.command_id] = task
                        task.add_done_callback(self._discard_task(command.command_id))
                    elif frame_type == "cancel":
                        cancellation = validate_wire_model(CancelCommand, payload)
                        if cancellation.session_id != welcome.session_id:
                            raise ValueError("stale satellite session")
                        if (
                            not self.execution_engine.cancel(cancellation.command_id)
                            and cancellation.command_id in self._tasks
                        ):
                            self._cancel_before_start.add(cancellation.command_id)
                    elif frame_type == "heartbeat_ack":
                        ack = validate_wire_model(HeartbeatAck, payload)
                        if ack.session_id != welcome.session_id:
                            raise ValueError("stale satellite session")
                    else:
                        raise ValueError("unexpected core frame")
            finally:
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)
                self.logger.info("satellite session disconnected")

    async def _heartbeat_loop(self, websocket: ClientConnection, session_id: UUID) -> None:
        sequence = 0
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            sequence += 1
            frame = SatelliteHeartbeat(
                session_id=session_id,
                sequence=sequence,
                sent_at=datetime.now(UTC),
            )
            async with self._send_lock:
                await websocket.send(frame.model_dump_json())

    async def _handle_command(self, websocket: ClientConnection, command: ToolCommand) -> None:
        async with self._semaphore:
            try:
                replay = self.replay_journal.lookup(command)
            except ReplayConflictError:
                observation = self._failure(command, "replay_digest_mismatch")
            else:
                if isinstance(replay, CommandObservationFrame):
                    observation = replay
                elif replay == "consequential_outcome_uncertain":
                    observation = self._failure(
                        command,
                        "consequential_outcome_uncertain",
                        uncertain=True,
                    )
                elif command.command_id in self._cancel_before_start:
                    self._cancel_before_start.discard(command.command_id)
                    observation = CommandObservationFrame(
                        session_id=command.session_id,
                        command_id=command.command_id,
                        name=command.name,
                        version=command.version,
                        argument_digest=command.argument_digest,
                        status=ToolObservationStatus.CANCELLED,
                        output={},
                        verification={"verified": True, "cancelled_before_start": True},
                        failure_code="cancelled",
                        observed_at=datetime.now(UTC),
                    )
                else:
                    self.replay_journal.begin(command)
                    observation = await asyncio.to_thread(self.execution_engine.execute, command)
                    self.replay_journal.finish(command, observation)
            try:
                await self._send_observation(websocket, observation)
            except ConnectionClosed:
                return

    async def _send_observation(
        self,
        websocket: ClientConnection,
        observation: CommandObservationFrame,
    ) -> None:
        async with self._send_lock:
            await websocket.send(observation.model_dump_json())

    def _discard_task(self, command_id: UUID) -> Callable[[asyncio.Task[None]], None]:
        def discard(_: asyncio.Task[None]) -> None:
            self._tasks.pop(command_id, None)

        return discard

    @staticmethod
    def _failure(
        command: ToolCommand, code: str, *, uncertain: bool = False
    ) -> CommandObservationFrame:
        return CommandObservationFrame(
            session_id=command.session_id,
            command_id=command.command_id,
            name=command.name,
            version=command.version,
            argument_digest=command.argument_digest,
            status=ToolObservationStatus.FAILED,
            output={},
            verification={"verified": False, "uncertain_outcome": uncertain},
            failure_code=code,
            observed_at=datetime.now(UTC),
        )

    @staticmethod
    def _decode(raw: str | bytes) -> dict[str, Any]:
        encoded = raw.encode("utf-8") if isinstance(raw, str) else raw
        if len(encoded) > MAX_FRAME_BYTES:
            raise ValueError("satellite frame exceeds bound")

        def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            value: dict[str, Any] = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("duplicate JSON key")
                value[key] = item
            return value

        value = json.loads(encoded, object_pairs_hook=reject_duplicate_keys)
        if not isinstance(value, dict):
            raise ValueError("satellite frame must be an object")
        return value


__all__ = ["WindowsSatelliteAgent"]
