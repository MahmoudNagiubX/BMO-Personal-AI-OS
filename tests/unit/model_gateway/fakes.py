"""Deterministic local provider fakes for gateway tests."""

from __future__ import annotations

import threading
from collections.abc import Sequence

from personal_ai_os.model_gateway.contracts import (
    ProviderEmbeddingResult,
    ProviderGenerationRequest,
    ProviderGenerationResult,
    ProviderModel,
)
from personal_ai_os.model_gateway.registry import ACTIVE_MODELS


def finite_vectors(count: int, dimension: int = 1024) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(float(index % 7) for index in range(dimension)) for _ in range(count))


class FakeProvider:
    """Configurable fake implementing only the Phase 5A provider protocol."""

    def __init__(self) -> None:
        self.version_value = "0.32.5"
        self.models: tuple[ProviderModel, ...] = tuple(
            ProviderModel(model_id=model.model_id, digest=model.digest) for model in ACTIVE_MODELS
        )
        self.generation_result = ProviderGenerationResult(
            text="synthetic response",
            finish_reason="stop",
            prompt_tokens=4,
            output_tokens=2,
        )
        self.embedding_result = ProviderEmbeddingResult(vectors=finite_vectors(1))
        self.version_failures: list[Exception] = []
        self.inventory_failures: list[Exception] = []
        self.generation_failures: list[Exception] = []
        self.embedding_failures: list[Exception] = []
        self.version_calls = 0
        self.inventory_calls = 0
        self.generation_calls = 0
        self.embedding_calls = 0
        self.last_generation: ProviderGenerationRequest | None = None
        self.last_embedding_texts: tuple[str, ...] | None = None
        self.generation_timeouts: list[float] = []
        self.embedding_timeouts: list[float] = []
        self.entered: threading.Event | None = None
        self.release: threading.Event | None = None
        self.active_calls = 0
        self.max_active_calls = 0
        self._lock = threading.Lock()

    def version(self, *, timeout_seconds: float) -> str:
        del timeout_seconds
        self.version_calls += 1
        self._raise_next(self.version_failures)
        return self.version_value

    def inventory(self, *, timeout_seconds: float) -> Sequence[ProviderModel]:
        del timeout_seconds
        self.inventory_calls += 1
        self._raise_next(self.inventory_failures)
        return self.models

    def generate(
        self,
        request: ProviderGenerationRequest,
        *,
        timeout_seconds: float,
    ) -> ProviderGenerationResult:
        self.generation_timeouts.append(timeout_seconds)
        self.generation_calls += 1
        self.last_generation = request
        self._raise_next(self.generation_failures)
        self._block_if_configured()
        return self.generation_result

    def embed(
        self,
        model_id: str,
        texts: tuple[str, ...],
        *,
        timeout_seconds: float,
    ) -> ProviderEmbeddingResult:
        del model_id
        self.embedding_timeouts.append(timeout_seconds)
        self.embedding_calls += 1
        self.last_embedding_texts = texts
        self._raise_next(self.embedding_failures)
        self._block_if_configured()
        return self.embedding_result

    def _block_if_configured(self) -> None:
        if self.entered is None or self.release is None:
            return
        with self._lock:
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
        self.entered.set()
        self.release.wait(timeout=2)
        with self._lock:
            self.active_calls -= 1

    @staticmethod
    def _raise_next(failures: list[Exception]) -> None:
        if failures:
            raise failures.pop(0)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds
