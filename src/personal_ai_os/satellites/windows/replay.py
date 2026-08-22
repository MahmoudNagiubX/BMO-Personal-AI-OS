"""Bounded replay and crash-uncertainty journal without personal result persistence."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock
from uuid import UUID

from personal_ai_os.satellites.windows.contracts import CommandObservationFrame, ToolCommand

_CONSEQUENTIAL_TOOLS = {"windows.workflow.start"}


class ReplayConflictError(RuntimeError):
    pass


class ReplayJournal:
    """Cache terminal frames in memory and persist only consequential digest/state facts."""

    def __init__(self, path: Path, *, maximum_records: int = 256) -> None:
        self.path = path
        self.maximum_records = maximum_records
        self._lock = RLock()
        self._terminal: dict[UUID, CommandObservationFrame] = {}
        self._durable = self._load()

    def _load(self) -> dict[str, dict[str, str]]:
        if not self.path.is_file():
            return {}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("replay journal is invalid")
        result: dict[str, dict[str, str]] = {}
        for key, record in value.items():
            UUID(key)
            if not isinstance(record, dict) or set(record) != {"name", "digest", "state"}:
                raise ValueError("replay journal record is invalid")
            if record["state"] not in {"in_flight", "terminal"}:
                raise ValueError("replay journal state is invalid")
            result[key] = {field: str(record[field]) for field in record}
        return result

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self._durable, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    def lookup(self, command: ToolCommand) -> CommandObservationFrame | str | None:
        with self._lock:
            terminal = self._terminal.get(command.command_id)
            if terminal is not None:
                if (
                    terminal.name != command.name
                    or terminal.version != command.version
                    or terminal.argument_digest != command.argument_digest
                ):
                    raise ReplayConflictError("replay_digest_mismatch")
                return terminal.model_copy(update={"session_id": command.session_id})
            record = self._durable.get(str(command.command_id))
            if record is None:
                return None
            if record["name"] != command.name or record["digest"] != command.argument_digest:
                raise ReplayConflictError("replay_digest_mismatch")
            if command.name in _CONSEQUENTIAL_TOOLS:
                return "consequential_outcome_uncertain"
            return None

    def begin(self, command: ToolCommand) -> None:
        if command.name not in _CONSEQUENTIAL_TOOLS:
            return
        with self._lock:
            self._durable[str(command.command_id)] = {
                "name": command.name,
                "digest": command.argument_digest,
                "state": "in_flight",
            }
            self._trim()
            self._persist()

    def finish(self, command: ToolCommand, observation: CommandObservationFrame) -> None:
        with self._lock:
            self._terminal[command.command_id] = observation
            if command.name in _CONSEQUENTIAL_TOOLS:
                self._durable[str(command.command_id)] = {
                    "name": command.name,
                    "digest": command.argument_digest,
                    "state": "terminal",
                }
                self._trim()
                self._persist()

    def _trim(self) -> None:
        while len(self._durable) > self.maximum_records:
            self._durable.pop(next(iter(self._durable)))
        while len(self._terminal) > self.maximum_records:
            self._terminal.pop(next(iter(self._terminal)))


__all__ = ["ReplayConflictError", "ReplayJournal"]
