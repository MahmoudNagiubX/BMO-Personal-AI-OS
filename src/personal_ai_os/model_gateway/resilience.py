"""Small deterministic in-process resilience primitives."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from enum import StrEnum

from personal_ai_os.model_gateway.contracts import ModelIdentity, Provider
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

    def record_non_transient_result(self) -> None:
        """Release an admitted half-open probe without misclassifying its error."""

        with self._lock:
            if self._state is CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._opened_at = None
                self._half_open_probe_active = False

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


class ResidencyCoordinator:
    """Keep the one-heavy-model physical residency invariant at the gateway boundary."""

    def __init__(self, providers: Mapping[Provider, object], *, wait_seconds: float) -> None:
        self._providers = providers
        self._lock = threading.Lock()
        self._wait_seconds = wait_seconds

    def prepare(self, identity: ModelIdentity, *, timeout_seconds: float) -> None:
        """Prepare the requested provider without silently falling back."""

        with self._lock:
            if identity.provider is Provider.LLAMA_CPP:
                ollama = self._providers.get(Provider.OLLAMA)
                resident_models = getattr(ollama, "resident_models", None)
                if callable(resident_models) and resident_models(timeout_seconds=timeout_seconds):
                    raise ModelGatewayError(
                        GatewayErrorCategory.PROVIDER_UNAVAILABLE,
                        "fast_model_resident",
                        "the advanced provider requires the fast model to be unloaded",
                    )
                advanced = self._providers.get(Provider.LLAMA_CPP)
                ensure_awake = getattr(advanced, "ensure_awake", None)
                if callable(ensure_awake):
                    ensure_awake(timeout_seconds=timeout_seconds)
                return

            advanced = self._providers.get(Provider.LLAMA_CPP)
            ensure_sleeping = getattr(advanced, "ensure_sleeping", None)
            if callable(ensure_sleeping) and not ensure_sleeping(timeout_seconds=timeout_seconds):
                raise ModelGatewayError(
                    GatewayErrorCategory.PROVIDER_UNAVAILABLE,
                    "advanced_model_not_sleeping",
                    "the advanced provider did not confirm unloaded residency",
                )


__all__ = ["CircuitBreaker", "CircuitState", "InferenceGuard", "ResidencyCoordinator"]
