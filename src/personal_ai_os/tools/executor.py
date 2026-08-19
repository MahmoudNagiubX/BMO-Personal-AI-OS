"""Typed synthetic executors used only for Phase 8 acceptance."""

from __future__ import annotations

from datetime import UTC, datetime

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


__all__ = ["SyntheticToolExecutor"]
