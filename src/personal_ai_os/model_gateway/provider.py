"""Narrow provider protocol and internal normalized transport failures."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from personal_ai_os.model_gateway.contracts import (
    ProviderEmbeddingResult,
    ProviderGenerationRequest,
    ProviderGenerationResult,
    ProviderModel,
)


class ProviderError(RuntimeError):
    """Sanitized provider-adapter failure; raw responses never cross this boundary."""


class ProviderOfflineError(ProviderError):
    """Provider listener is unreachable."""


class ProviderTimeoutError(ProviderError):
    """Provider exceeded the bounded operation timeout."""


class ProviderTransientError(ProviderError):
    """Provider returned a retryable local failure."""


class ProviderRequestError(ProviderError):
    """Provider deterministically rejected the request."""


class ProviderContractError(ProviderError):
    """Provider response did not satisfy the adapter contract."""


class ModelProvider(Protocol):
    """Only the provider operations authorized in Phase 5A."""

    def version(self, *, timeout_seconds: float) -> str: ...

    def inventory(self, *, timeout_seconds: float) -> Sequence[ProviderModel]: ...

    def generate(
        self,
        request: ProviderGenerationRequest,
        *,
        timeout_seconds: float,
    ) -> ProviderGenerationResult: ...

    def embed(
        self,
        model_id: str,
        texts: tuple[str, ...],
        *,
        timeout_seconds: float,
    ) -> ProviderEmbeddingResult: ...


__all__ = [
    "ModelProvider",
    "ProviderContractError",
    "ProviderError",
    "ProviderOfflineError",
    "ProviderRequestError",
    "ProviderTimeoutError",
    "ProviderTransientError",
]
