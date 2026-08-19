"""Small strict schemas used by the synthetic Phase 8 catalog."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, StrictBool, StrictInt, StrictStr

from personal_ai_os.identity.contracts import StrictContract


class StatusArguments(StrictContract):
    resource: Literal["platform"]


class ReversibleArguments(StrictContract):
    value: StrictInt = Field(ge=0, le=100)


class ConsequentialArguments(StrictContract):
    message: StrictStr = Field(min_length=1, max_length=200)


class CriticalArguments(StrictContract):
    message: StrictStr = Field(min_length=1, max_length=200)
    confirmation: Literal["owner-confirmed"]


class EmptyArguments(StrictContract):
    pass


class StatusOutput(StrictContract):
    ok: StrictBool
    state: Literal["ready"]


class ReversibleOutput(StrictContract):
    ok: StrictBool
    value: StrictInt


class MessageOutput(StrictContract):
    ok: StrictBool
    message: StrictStr


__all__ = [
    "ConsequentialArguments",
    "CriticalArguments",
    "EmptyArguments",
    "MessageOutput",
    "ReversibleArguments",
    "ReversibleOutput",
    "StatusArguments",
    "StatusOutput",
]
