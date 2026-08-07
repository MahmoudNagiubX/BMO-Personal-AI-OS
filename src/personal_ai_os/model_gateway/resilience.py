"""Small deterministic in-process resilience primitives."""

from __future__ import annotations

import threading
from collections.abc import Callable
from enum import StrEnum

from personal_ai_os.model_gateway.errors import GatewayErrorCategory, ModelGatewayError


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Thread-safe closed/open/half-open circuit breaker using a monotonic clock."""

    def __init__(
        self,
        *,
        failure_threshold: int,
        cooldown_seconds: float,
        clock: Callable[[], float],
    ) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: float | None = None
        self._half_open_probe_active = False
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state

    @property
    def failure_count(self) -> int:
        with self._lock:
            return self._failure_count

    def before_call(self) -> None:
        """Permit a call or fail fast while the circuit is unavailable."""

        with self._lock:
            if self._state is CircuitState.OPEN:
                assert self._opened_at is not None
                if self._clock() - self._opened_at < self._cooldown_seconds:
                    raise ModelGatewayError(
                        GatewayErrorCategory.PROVIDER_UNAVAILABLE,
                        "circuit_open",
                        "the local model provider circuit is open",
                    )
                self._state = CircuitState.HALF_OPEN
                self._half_open_probe_active = True
                return
            if self._state is CircuitState.HALF_OPEN:
                if self._half_open_probe_active:
                    raise ModelGatewayError(
                        GatewayErrorCategory.PROVIDER_UNAVAILABLE,
                        "circuit_probe_in_progress",
                        "the local model provider circuit probe is in progress",
                    )
                self._half_open_probe_active = True

    def record_success(self) -> None:
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._opened_at = None
            self._half_open_probe_active = False

    def record_transient_failure(self) -> None:
        with self._lock:
            if self._state is CircuitState.HALF_OPEN:
                self._open()
                return
            self._failure_count += 1
            if self._failure_count >= self._failure_threshold:
                self._open()

    def _open(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = self._clock()
        self._half_open_probe_active = False


class InferenceGuard:
    """Enforce the Phase 4 one-request-at-a-time runtime profile."""

    def __init__(self, *, wait_seconds: float) -> None:
        self._wait_seconds = wait_seconds
        self._semaphore = threading.BoundedSemaphore(value=1)

    def __enter__(self) -> InferenceGuard:
        if not self._semaphore.acquire(timeout=self._wait_seconds):
            raise ModelGatewayError(
                GatewayErrorCategory.BUSY,
                "inference_busy",
                "the local model provider is serving another request",
            )
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self._semaphore.release()


__all__ = ["CircuitBreaker", "CircuitState", "InferenceGuard"]
