"""Product-owned model gateway error categories."""

from __future__ import annotations

from enum import StrEnum


class GatewayErrorCategory(StrEnum):
    """Stable categories callers can handle without provider knowledge."""

    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    TIMEOUT = "timeout"
    PROVIDER_TRANSIENT_FAILURE = "provider_transient_failure"
    PROVIDER_CONTRACT_VIOLATION = "provider_contract_violation"
    STRUCTURED_OUTPUT_INVALID = "structured_output_invalid"
    MODEL_IDENTITY_MISMATCH = "model_identity_mismatch"
    BUSY = "busy"


class ModelGatewayError(RuntimeError):
    """Sanitized gateway failure with a stable category and reason code."""

    def __init__(
        self,
        category: GatewayErrorCategory,
        reason_code: str,
        message: str,
        *,
        attempts: int = 0,
    ) -> None:
        self.category = category
        self.reason_code = reason_code
        self.attempts = attempts
        super().__init__(f"{category.value}: {message}")


__all__ = ["GatewayErrorCategory", "ModelGatewayError"]
