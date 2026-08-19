"""Static versioned Phase 8 tool registry and canonical argument binding."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from personal_ai_os.tools.contracts import (
    ApprovalPolicy,
    RiskLevel,
    SandboxPolicy,
)
from personal_ai_os.tools.errors import ToolNotFoundError, ToolSchemaError
from personal_ai_os.tools.schemas import (
    ConsequentialArguments,
    CriticalArguments,
    EmptyArguments,
    MessageOutput,
    ReversibleArguments,
    ReversibleOutput,
    StatusArguments,
    StatusOutput,
)

_Model = TypeVar("_Model", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    """Immutable policy descriptor; no caller can override these fields."""

    name: str
    version: int
    description: str
    owner_kind: str
    execution_target: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    required_request_scopes: frozenset[str]
    required_device_capabilities: frozenset[str]
    risk_level: RiskLevel
    approval_policy: ApprovalPolicy
    availability_policy: str
    timeout_seconds: float
    idempotency_policy: str
    rate_limit_policy: tuple[int, int]
    budget_cost: int
    audit_redaction_policy: str
    verification_policy: str
    reversal_policy: str
    sandbox_policy: SandboxPolicy
    enabled: bool = True

    def __post_init__(self) -> None:
        if (
            self.risk_level in {RiskLevel.CONSEQUENTIAL, RiskLevel.CRITICAL}
            and self.approval_policy is not ApprovalPolicy.EXACT_OWNER
        ):
            raise ValueError(
                "consequential and critical tools require exact_owner approval, "
                f"got {self.approval_policy}"
            )

    @property
    def rate_limit(self) -> dict[str, int]:
        return {
            "max_requests": self.rate_limit_policy[0],
            "window_seconds": self.rate_limit_policy[1],
        }

    def input_schema(self) -> dict[str, Any]:
        return self.input_model.model_json_schema()

    def output_schema(self) -> dict[str, Any]:
        return self.output_model.model_json_schema()


class ToolRegistry:
    """Exact name/version lookup with no wildcard or model-defined entries."""

    def __init__(self, descriptors: tuple[ToolDescriptor, ...]) -> None:
        self._descriptors = {(item.name, item.version): item for item in descriptors}
        if len(self._descriptors) != len(descriptors):
            raise ValueError("tool registry contains a duplicate name/version")

    def resolve(self, name: str, version: int) -> ToolDescriptor:
        descriptor = self._descriptors.get((name, version))
        if descriptor is None:
            raise ToolNotFoundError("unknown_tool_version")
        return descriptor

    def catalog(self) -> tuple[ToolDescriptor, ...]:
        return tuple(sorted(self._descriptors.values(), key=lambda item: (item.name, item.version)))

    def validate_arguments(self, descriptor: ToolDescriptor, arguments: object) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise ToolSchemaError("arguments_not_object")
        try:
            model = descriptor.input_model.model_validate(arguments, strict=True)
        except ValidationError as error:
            raise ToolSchemaError("input_schema_invalid") from error
        return model.model_dump(mode="json")

    def validate_output(self, descriptor: ToolDescriptor, output: object) -> dict[str, Any]:
        try:
            model = descriptor.output_model.model_validate(output, strict=True)
        except ValidationError as error:
            raise ToolSchemaError("output_schema_invalid") from error
        return model.model_dump(mode="json")


def canonical_arguments(arguments: dict[str, Any]) -> str:
    """Return the only argument representation eligible for authority binding."""

    try:
        return json.dumps(arguments, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ToolSchemaError("arguments_not_canonicalizable") from error


def argument_digest(arguments: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_arguments(arguments).encode("utf-8")).hexdigest()


SENSITIVE_KEY_TOKENS = (
    "secret",
    "token",
    "password",
    "credential",
    "authorization",
    "api_key",
    "private_key",
    "cookie",
    "session_cookie",
)


def deterministic_preview(descriptor: ToolDescriptor, arguments: dict[str, Any]) -> dict[str, Any]:
    """Create a stable redacted preview without retaining raw secret-like values."""

    redacted: dict[str, Any] = {}
    for key in sorted(arguments):
        value = arguments[key]
        if any(token in key.casefold() for token in SENSITIVE_KEY_TOKENS):
            redacted[key] = "[REDACTED]"
        else:
            redacted[key] = value
    return {
        "tool": descriptor.name,
        "version": descriptor.version,
        "risk": descriptor.risk_level.value,
        "arguments": redacted,
        "argument_digest": argument_digest(arguments),
    }


def _descriptor(
    name: str,
    description: str,
    input_model: type[BaseModel],
    output_model: type[BaseModel],
    risk: RiskLevel,
    *,
    approval: ApprovalPolicy = ApprovalPolicy.NONE,
    availability: str = "local_ready",
    sandbox: SandboxPolicy = SandboxPolicy.CORE_READONLY,
    enabled: bool = True,
    max_requests: int = 10,
    window_seconds: int = 60,
) -> ToolDescriptor:
    return ToolDescriptor(
        name=name,
        version=1,
        description=description,
        owner_kind="bmo_core",
        execution_target="synthetic_phase8_executor",
        input_model=input_model,
        output_model=output_model,
        required_request_scopes=frozenset({"tool.request"}),
        required_device_capabilities=frozenset(),
        risk_level=risk,
        approval_policy=approval,
        availability_policy=availability,
        timeout_seconds=5.0,
        idempotency_policy="required_exact_key_and_argument_digest",
        rate_limit_policy=(max_requests, window_seconds),
        budget_cost=1,
        audit_redaction_policy="structured_digest_and_secret_key_redaction",
        verification_policy="typed_output_and_executor_verification",
        reversal_policy="none_for_synthetic_demo",
        sandbox_policy=sandbox,
        enabled=enabled,
    )


def default_registry() -> ToolRegistry:
    """Return the complete static catalog, including disabled denial fixtures."""

    return ToolRegistry(
        (
            _descriptor(
                "phase8.status.read",
                "Read a synthetic bounded platform status.",
                StatusArguments,
                StatusOutput,
                RiskLevel.READ,
            ),
            _descriptor(
                "phase8.reversible.set",
                "Set a synthetic bounded reversible value.",
                ReversibleArguments,
                ReversibleOutput,
                RiskLevel.REVERSIBLE,
            ),
            _descriptor(
                "phase8.consequential.echo",
                "Record a synthetic consequential message after owner approval.",
                ConsequentialArguments,
                MessageOutput,
                RiskLevel.CONSEQUENTIAL,
                approval=ApprovalPolicy.EXACT_OWNER,
                max_requests=4,
            ),
            _descriptor(
                "phase8.critical.echo",
                "Record a synthetic critical message after owner approval.",
                CriticalArguments,
                MessageOutput,
                RiskLevel.CRITICAL,
                approval=ApprovalPolicy.EXACT_OWNER,
                max_requests=2,
            ),
            _descriptor(
                "phase8.offline.read",
                "Synthetic read whose provider is intentionally offline.",
                EmptyArguments,
                StatusOutput,
                RiskLevel.READ,
                availability="offline",
            ),
            _descriptor(
                "phase8.uncertain.outcome",
                "Synthetic executor fixture for uncertain executor outcome.",
                EmptyArguments,
                StatusOutput,
                RiskLevel.READ,
            ),
            _descriptor(
                "phase8.invalid.output",
                "Synthetic executor fixture for output validation failure.",
                EmptyArguments,
                StatusOutput,
                RiskLevel.READ,
            ),
            _descriptor(
                "phase8.verification.fail",
                "Synthetic executor fixture for verification failure.",
                EmptyArguments,
                StatusOutput,
                RiskLevel.READ,
            ),
            _descriptor(
                "phase8.slow.cancellable",
                "Synthetic bounded slow reversible operation.",
                EmptyArguments,
                StatusOutput,
                RiskLevel.REVERSIBLE,
                max_requests=2,
            ),
            _descriptor(
                "phase8.forbidden.shell",
                "Explicit denial fixture; no shell executor exists.",
                EmptyArguments,
                StatusOutput,
                RiskLevel.FORBIDDEN_AUTONOMOUS,
                sandbox=SandboxPolicy.FORBIDDEN,
                enabled=False,
            ),
        )
    )


__all__ = [
    "ToolDescriptor",
    "ToolRegistry",
    "argument_digest",
    "canonical_arguments",
    "default_registry",
    "deterministic_preview",
]
