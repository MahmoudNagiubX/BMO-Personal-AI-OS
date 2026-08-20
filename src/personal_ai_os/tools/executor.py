"""Descriptor-selected typed executor boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from personal_ai_os.tools.contracts import (
    ToolExecutionRequest,
    ToolObservation,
    ToolObservationStatus,
)


class SyntheticToolExecutor:
    """A deterministic in-process fake; it has no filesystem, network, or shell access."""

    def execute(self, request: ToolExecutionRequest) -> ToolObservation:
        now = datetime.now(UTC)
        if request.name == "phase8.invalid.output":
            return ToolObservation(
                status=ToolObservationStatus.SUCCEEDED,
                output={"not_the_declared_shape": True},
                verification={"verified": True},
                observed_at=now,
            )
        if request.name == "phase8.uncertain.outcome":
            raise RuntimeError("synthetic_executor_uncertain_crash")
        if request.name == "phase8.verification.fail":
            return ToolObservation(
                status=ToolObservationStatus.SUCCEEDED,
                output={"ok": True, "state": "ready"},
                verification={"verified": False, "reason": "synthetic_verification_failure"},
                observed_at=now,
            )
        if request.name == "phase8.reversible.set":
            return ToolObservation(
                status=ToolObservationStatus.SUCCEEDED,
                output={"ok": True, "value": request.arguments["value"]},
                verification={"verified": True},
                observed_at=now,
            )
        if request.name in {
            "phase8.consequential.echo",
            "phase8.critical.echo",
        }:
            return ToolObservation(
                status=ToolObservationStatus.SUCCEEDED,
                output={"ok": True, "message": request.arguments["message"]},
                verification={"verified": True},
                observed_at=now,
            )
        if request.name == "phase8.slow.cancellable":
            return ToolObservation(
                status=ToolObservationStatus.SUCCEEDED,
                output={"ok": True, "state": "ready"},
                verification={"verified": True, "bounded": True},
                observed_at=now,
            )
        return ToolObservation(
            status=ToolObservationStatus.SUCCEEDED,
            output={"ok": True, "state": "ready"},
            verification={"verified": True},
            observed_at=now,
        )

    def cancel(self, tool_call_id: UUID) -> bool:
        """Synthetic executions have no independently cancellable child process."""

        del tool_call_id
        return False


class ToolExecutor(Protocol):
    def execute(self, request: ToolExecutionRequest) -> ToolObservation: ...


class ExecutorRouter:
    """Route only by the immutable descriptor-selected execution target."""

    def __init__(self, executors: dict[str, ToolExecutor]) -> None:
        self._executors = dict(executors)

    def execute(self, request: ToolExecutionRequest) -> ToolObservation:
        executor = self._executors.get(request.execution_target)
        if executor is None:
            raise RuntimeError("executor_target_unavailable")
        return executor.execute(request)

    def cancel(self, execution_target: str, tool_call_id: UUID) -> bool:
        executor = self._executors.get(execution_target)
        if executor is None:
            return False
        cancellation = getattr(executor, "cancel", None)
        if cancellation is None:
            return False
        return bool(cancellation(tool_call_id))


__all__ = ["ExecutorRouter", "SyntheticToolExecutor", "ToolExecutor"]
