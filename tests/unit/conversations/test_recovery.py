from __future__ import annotations

from threading import Event, Lock, Thread
from time import sleep
from typing import Any

from personal_ai_os.conversations.reconciliation import ConversationReconciliationGate


class _SessionContext:
    def __enter__(self) -> object:
        return object()

    def __exit__(self, *_: object) -> None:
        return None


class _Factory:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> _SessionContext:
        self.calls += 1
        return _SessionContext()


def test_reconciliation_gate_defers_then_retries_with_fresh_session(
    monkeypatch: Any,
) -> None:
    gate = ConversationReconciliationGate()
    factory = _Factory()
    outcomes = iter([RuntimeError("database unavailable"), None])

    def reconcile(_: object) -> None:
        outcome = next(outcomes)
        if outcome is not None:
            raise outcome

    monkeypatch.setattr(
        "personal_ai_os.conversations.reconciliation.ConversationService.reconcile_interrupted_runs",
        reconcile,
    )

    assert gate.attempt(factory) is False
    assert gate.ready is False
    assert gate.deferred is True
    assert gate.attempts == 1
    assert gate.ensure_ready(factory) is True
    assert gate.ready is True
    assert gate.deferred is False
    assert gate.attempts == 2
    assert factory.calls == 2


def test_reconciliation_gate_serializes_concurrent_recovery_attempts(monkeypatch: Any) -> None:
    gate = ConversationReconciliationGate()
    factory = _Factory()
    entered = Event()
    release = Event()
    active = 0
    maximum = 0
    guard = Lock()

    def reconcile(_: object) -> None:
        nonlocal active, maximum
        with guard:
            active += 1
            maximum = max(maximum, active)
        entered.set()
        release.wait(timeout=5)
        with guard:
            active -= 1

    monkeypatch.setattr(
        "personal_ai_os.conversations.reconciliation.ConversationService.reconcile_interrupted_runs",
        reconcile,
    )
    results: list[bool] = []

    def attempt() -> None:
        results.append(gate.ensure_ready(factory))

    first = Thread(target=attempt)
    second = Thread(target=attempt)
    first.start()
    assert entered.wait(timeout=5)
    second.start()
    sleep(0.05)
    assert gate.attempts == 1
    release.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert sorted(results) == [True, True]
    assert gate.attempts == 1
    assert maximum == 1
