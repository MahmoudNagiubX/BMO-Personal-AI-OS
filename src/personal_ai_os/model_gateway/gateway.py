"""Deterministic, fail-closed multi-provider model gateway."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Never, TypeVar

from personal_ai_os.model_gateway.config import GatewaySettings
from personal_ai_os.model_gateway.contracts import (
    Availability,
    Capability,
    EmbeddingRequest,
    EmbeddingResponse,
    GenerationRequest,
    GenerationResponse,
    HealthReason,
    HealthSnapshot,
    ImageInput,
    Message,
    MessageRole,
    Modality,
    ModelIdentity,
    ModelPresence,
    Provider,
    ProviderEmbeddingResult,
    ProviderGenerationRequest,
    ProviderGenerationResult,
    ProviderModel,
    ToolDefinition,
    ToolProposal,
    Usage,
)
from personal_ai_os.model_gateway.errors import GatewayErrorCategory, ModelGatewayError
from personal_ai_os.model_gateway.provider import (
    ModelProvider,
    ProviderContractError,
    ProviderOfflineError,
    ProviderRequestError,
    ProviderTimeoutError,
    ProviderTransientError,
)
from personal_ai_os.model_gateway.registry import (
    ACTIVE_MODELS,
    OPTIONAL_MODELS,
    QWEN_4B,
    route_model,
)
from personal_ai_os.model_gateway.resilience import (
    CircuitBreaker,
    InferenceGuard,
    ResidencyCoordinator,
)
from personal_ai_os.model_gateway.validation import (
    require_identifier,
    require_tool_name,
    validate_schema,
    validate_structured_value,
)

_T = TypeVar("_T")
_SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}


class ModelGateway:
    """Coordinate validation, routing, provider isolation, and local residency."""

    def __init__(
        self,
        provider: ModelProvider | Mapping[Provider, ModelProvider],
        settings: GatewaySettings | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if isinstance(provider, Mapping):
            self._providers = dict(provider)
        else:
            # Backward-compatible construction for the Phase 5A single Ollama provider.
            self._providers = {Provider.OLLAMA: provider}
        self.settings = settings or GatewaySettings()
        self._clock = clock
        self._sleeper = sleeper
        self._circuits: dict[tuple[Provider, str], CircuitBreaker] = {}
        for identity in (*ACTIVE_MODELS, *OPTIONAL_MODELS):
            self._circuits[(identity.provider, identity.model_id)] = self._new_circuit(clock)
        self.circuit = self._circuits[(Provider.OLLAMA, QWEN_4B.model_id)]
        self._guard = InferenceGuard(wait_seconds=self.settings.concurrency_wait_seconds)
        self._residency = ResidencyCoordinator(
            self._providers, wait_seconds=self.settings.concurrency_wait_seconds
        )

    def circuit_for(self, identity: ModelIdentity) -> CircuitBreaker:
        """Return the isolated circuit associated with one provider/model identity."""

        return self._circuit_for(identity)

    def health(self) -> HealthSnapshot:
        """Report required core health and optional advanced health independently."""

        started = self._clock()
        if not self.settings.enabled:
            return self._health_snapshot(
                started,
                Availability.OFFLINE,
                HealthReason.GATEWAY_DISABLED,
                (),
                optional_models=self._missing_optional_models(),
                optional_availability=Availability.OFFLINE,
            )

        core_provider = self._providers.get(Provider.OLLAMA)
        if core_provider is None:
            return self._health_snapshot(
                started,
                Availability.OFFLINE,
                HealthReason.PROVIDER_UNREACHABLE,
                (),
                optional_models=self._missing_optional_models(),
            )
        try:
            version = core_provider.version(timeout_seconds=self.settings.health_timeout_seconds)
            inventory = tuple(
                core_provider.inventory(timeout_seconds=self.settings.health_timeout_seconds)
            )
            presence = tuple(self._model_presence(model, inventory) for model in ACTIVE_MODELS)
        except ProviderTimeoutError:
            return self._health_snapshot(
                started,
                Availability.OFFLINE,
                HealthReason.PROVIDER_TIMEOUT,
                (),
                optional_models=self._missing_optional_models(),
            )
        except (ProviderOfflineError, ProviderTransientError):
            return self._health_snapshot(
                started,
                Availability.OFFLINE,
                HealthReason.PROVIDER_UNREACHABLE,
                (),
                optional_models=self._missing_optional_models(),
            )
        except (ProviderContractError, ProviderRequestError, AttributeError, TypeError):
            return self._health_snapshot(
                started,
                Availability.DEGRADED,
                HealthReason.PROVIDER_CONTRACT_VIOLATION,
                (),
                optional_models=self._missing_optional_models(),
            )
        except Exception:
            return self._health_snapshot(
                started,
                Availability.DEGRADED,
                HealthReason.PROVIDER_CONTRACT_VIOLATION,
                (),
                optional_models=self._missing_optional_models(),
            )

        if version != self.settings.expected_ollama_version:
            availability = Availability.DEGRADED
            reason = HealthReason.PROVIDER_VERSION_MISMATCH
        elif any(not item.present for item in presence):
            availability = Availability.DEGRADED
            reason = HealthReason.MODEL_MISSING
        elif any(not item.identity_matches for item in presence):
            availability = Availability.DEGRADED
            reason = HealthReason.MODEL_IDENTITY_MISMATCH
        else:
            availability = Availability.AVAILABLE
            reason = HealthReason.READY

        optional_models, optional_availability, optional_reason, optional_version = (
            self._optional_health()
        )
        return self._health_snapshot(
            started,
            availability,
            reason,
            presence,
            version,
            optional_models=optional_models,
            optional_availability=optional_availability,
            optional_reason=optional_reason,
            optional_provider_version=optional_version,
        )

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        """Execute one bounded generation request with no fallback or tool execution."""

        identity, timeout = self._validate_generation_request(request)
        provider = self._provider_for(identity)
        provider_request = ProviderGenerationRequest(
            model_id=identity.model_id,
            messages=request.messages,
            images=request.images,
            context_tokens=request.context_tokens,
            max_output_tokens=request.max_output_tokens,
            structured_schema=request.structured_schema,
            tools=request.tools,
        )
        started = self._clock()
        with self._guard:
            self._residency.prepare(identity, timeout_seconds=timeout)
            result, attempts = self._with_retry(
                lambda: self._generate_once(provider, identity, provider_request, timeout),
                self._circuit_for(identity),
            )
        response = self._normalize_generation(request, identity, result, started)
        if attempts < 1:
            raise AssertionError("a successful request must record an attempt")
        return response

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """Execute one bounded BGE-M3 embedding request."""

        identity, timeout = self._validate_embedding_request(request)
        provider = self._provider_for(identity)
        started = self._clock()
        with self._guard:
            self._residency.prepare(identity, timeout_seconds=timeout)
            result, attempts = self._with_retry(
                lambda: self._embed_once(provider, identity, request.texts, timeout),
                self._circuit_for(identity),
            )
        if attempts < 1:
            raise AssertionError("a successful request must record an attempt")
        vectors = self._normalize_vectors(identity, result)
        if len(vectors) != len(request.texts):
            self._provider_contract("embedding_count_invalid")
        return EmbeddingResponse(
            request_id=request.request_id,
            model=identity,
            vectors=vectors,
            dimension=identity.embedding_dimension or 0,
            count=len(vectors),
            latency_seconds=max(0.0, self._clock() - started),
        )

    def _provider_for(self, identity: ModelIdentity) -> ModelProvider:
        provider = self._providers.get(identity.provider)
        if provider is None:
            raise ModelGatewayError(
                GatewayErrorCategory.PROVIDER_UNAVAILABLE,
                "provider_offline",
                "the selected local provider is unavailable",
            )
        return provider

    def _generate_once(
        self,
        provider: ModelProvider,
        identity: ModelIdentity,
        request: ProviderGenerationRequest,
        timeout_seconds: float,
    ) -> ProviderGenerationResult:
        self._verify_identity(provider, identity, timeout_seconds)
        return provider.generate(request, timeout_seconds=timeout_seconds)

    def _embed_once(
        self,
        provider: ModelProvider,
        identity: ModelIdentity,
        texts: tuple[str, ...],
        timeout_seconds: float,
    ) -> ProviderEmbeddingResult:
        self._verify_identity(provider, identity, timeout_seconds)
        return provider.embed(identity.model_id, texts, timeout_seconds=timeout_seconds)

    def _with_retry(self, operation: Callable[[], _T], circuit: CircuitBreaker) -> tuple[_T, int]:
        for attempt in range(1, self.settings.max_attempts + 1):
            circuit.before_call()
            cause: BaseException | None = None
            try:
                result = operation()
            except ProviderOfflineError as exc:
                cause = exc
                error = ModelGatewayError(
                    GatewayErrorCategory.PROVIDER_UNAVAILABLE,
                    "provider_offline",
                    "the local model provider is unavailable",
                    attempts=attempt,
                )
                circuit.record_transient_failure()
            except ProviderTimeoutError as exc:
                cause = exc
                error = ModelGatewayError(
                    GatewayErrorCategory.TIMEOUT,
                    "provider_timeout",
                    "the local model provider timed out",
                    attempts=attempt,
                )
                circuit.record_transient_failure()
            except ProviderTransientError as exc:
                cause = exc
                error = ModelGatewayError(
                    GatewayErrorCategory.PROVIDER_TRANSIENT_FAILURE,
                    "provider_transient_failure",
                    "the local model provider failed transiently",
                    attempts=attempt,
                )
                circuit.record_transient_failure()
            except ProviderRequestError as exc:
                circuit.record_non_transient_result()
                raise ModelGatewayError(
                    GatewayErrorCategory.PROVIDER_CONTRACT_VIOLATION,
                    "provider_request_rejected",
                    "the local provider rejected the bounded request",
                    attempts=attempt,
                ) from exc
            except ProviderContractError as exc:
                circuit.record_non_transient_result()
                raise ModelGatewayError(
                    GatewayErrorCategory.PROVIDER_CONTRACT_VIOLATION,
                    "provider_contract_violation",
                    "the local provider response violated its contract",
                    attempts=attempt,
                ) from exc
            except ModelGatewayError:
                circuit.record_non_transient_result()
                raise
            except Exception as exc:
                circuit.record_non_transient_result()
                raise ModelGatewayError(
                    GatewayErrorCategory.PROVIDER_CONTRACT_VIOLATION,
                    "provider_contract_violation",
                    "the local provider violated the gateway boundary",
                    attempts=attempt,
                ) from exc
            else:
                circuit.record_success()
                return result, attempt

            if attempt >= self.settings.max_attempts:
                raise error from cause
            self._sleeper(self.settings.retry_backoff_seconds)
        raise AssertionError("bounded retry loop exited unexpectedly")

    def _verify_identity(
        self, provider: ModelProvider, expected: ModelIdentity, timeout_seconds: float
    ) -> None:
        inventory = provider.inventory(timeout_seconds=timeout_seconds)
        actual = next((item for item in inventory if item.model_id == expected.model_id), None)
        if actual is None:
            raise ModelGatewayError(
                GatewayErrorCategory.PROVIDER_UNAVAILABLE,
                "model_missing",
                "the required local model is not installed",
            )
        if actual.digest != expected.digest:
            raise ModelGatewayError(
                GatewayErrorCategory.MODEL_IDENTITY_MISMATCH,
                "model_identity_mismatch",
                "the installed local model digest does not match the registry",
            )

    def _validate_generation_request(
        self, request: GenerationRequest
    ) -> tuple[ModelIdentity, float]:
        if not self.settings.enabled:
            raise ModelGatewayError(
                GatewayErrorCategory.PROVIDER_UNAVAILABLE,
                "gateway_disabled",
                "the local model gateway is disabled",
            )
        require_identifier(request.request_id, name="request_id")
        if (
            not isinstance(request.messages, tuple)
            or not 1 <= len(request.messages) <= self.settings.max_messages
        ):
            self._invalid("invalid_message_count", "message count exceeds the gateway limit")
        total_text = 0
        for message in request.messages:
            if (
                not isinstance(message, Message)
                or not isinstance(message.role, MessageRole)
                or not isinstance(message.text, str)
                or not message.text.strip()
            ):
                self._invalid("invalid_message", "messages must contain bounded non-empty text")
            total_text += len(message.text)
        if total_text > self.settings.max_total_text_chars:
            self._invalid("text_limit_exceeded", "request text exceeds the gateway limit")
        if (
            not isinstance(request.max_output_tokens, int)
            or isinstance(request.max_output_tokens, bool)
            or not 1 <= request.max_output_tokens <= 256
        ):
            self._invalid("invalid_output_budget", "output budget is outside the accepted range")
        timeout_default = self.settings.generation_timeout_seconds
        timeout_maximum = timeout_default
        timeout = self._bounded_timeout(
            request.timeout_seconds, default=timeout_default, maximum=timeout_maximum
        )
        modalities = frozenset({Modality.TEXT})
        if request.images:
            modalities = frozenset({Modality.TEXT, Modality.IMAGE})
        identity = route_model(
            request.capability,
            modalities,
            requested_model=request.requested_model,
        )
        if request.context_tokens not in identity.context_budgets:
            self._invalid(
                "unsupported_context_budget", "context budget is not accepted by the model"
            )
        if request.max_output_tokens > identity.max_output_tokens:
            self._invalid("invalid_output_budget", "output budget exceeds the model profile")
        if request.context_tokens > 4096 and request.max_output_tokens > 32:
            self._invalid(
                "large_context_output_exceeded",
                "large-context requests must use at most 32 output tokens",
            )

        self._validate_images(request.capability, request.images)
        if request.capability is Capability.STRUCTURED_OUTPUT:
            if request.structured_schema is None or request.tools:
                self._invalid(
                    "invalid_structured_request",
                    "structured output requires one schema and no tools",
                )
            validate_schema(request.structured_schema)
        elif request.structured_schema is not None:
            self._invalid(
                "unexpected_structured_schema",
                "a structured schema is allowed only for structured output",
            )

        if request.capability is Capability.TOOL_CALL_PROPOSAL:
            if not request.tools or request.structured_schema is not None:
                self._invalid(
                    "invalid_tool_proposal_request",
                    "tool proposal requires definitions and no structured schema",
                )
            self._validate_tools(request.tools)
        elif request.tools:
            self._invalid(
                "unexpected_tools",
                "tool definitions are allowed only for proposal requests",
            )
        return identity, timeout

    def _validate_embedding_request(self, request: EmbeddingRequest) -> tuple[ModelIdentity, float]:
        if not self.settings.enabled:
            raise ModelGatewayError(
                GatewayErrorCategory.PROVIDER_UNAVAILABLE,
                "gateway_disabled",
                "the local model gateway is disabled",
            )
        require_identifier(request.request_id, name="request_id")
        if (
            not isinstance(request.texts, tuple)
            or not 1 <= len(request.texts) <= self.settings.max_embedding_batch_size
        ):
            self._invalid("invalid_embedding_batch", "embedding batch is outside the limit")
        total = 0
        for text in request.texts:
            if (
                not isinstance(text, str)
                or not text.strip()
                or len(text) > self.settings.max_embedding_text_chars
            ):
                self._invalid(
                    "invalid_embedding_text", "embedding text must be non-empty and bounded"
                )
            total += len(text)
        if total > self.settings.max_embedding_total_chars:
            self._invalid(
                "embedding_text_limit_exceeded", "embedding batch exceeds the gateway limit"
            )
        timeout = self._bounded_timeout(
            request.timeout_seconds,
            default=self.settings.embedding_timeout_seconds,
            maximum=self.settings.embedding_timeout_seconds,
        )
        identity = route_model(
            Capability.EMBEDDINGS,
            frozenset({Modality.TEXT}),
            requested_model=request.requested_model,
        )
        return identity, timeout

    def _validate_images(self, capability: Capability, images: tuple[ImageInput, ...]) -> None:
        if capability is Capability.VISION and not images:
            self._invalid("vision_image_required", "vision requires explicit image bytes")
        if capability is not Capability.VISION and images:
            self._invalid("unexpected_image", "images are allowed only for vision")
        if len(images) > self.settings.max_images:
            self._invalid("image_count_exceeded", "image count exceeds the gateway limit")
        total = 0
        for image in images:
            if (
                not isinstance(image, ImageInput)
                or image.media_type not in _SUPPORTED_IMAGE_TYPES
                or not isinstance(image.data, bytes)
                or not image.data
            ):
                self._invalid("invalid_image", "image input must be explicit supported bytes")
            total += len(image.data)
        if total > self.settings.max_image_bytes:
            self._invalid("image_size_exceeded", "image bytes exceed the gateway limit")

    def _validate_tools(self, tools: tuple[ToolDefinition, ...]) -> None:
        if len(tools) > 16:
            self._invalid("tool_count_exceeded", "tool definition count exceeds the limit")
        names: set[str] = set()
        for tool in tools:
            if not isinstance(tool, ToolDefinition):
                self._invalid("invalid_tool", "tool definitions must use the gateway contract")
            name = require_tool_name(tool.name)
            if name in names:
                self._invalid("duplicate_tool", "tool names must be unique")
            names.add(name)
            if not isinstance(tool.description, str) or not 1 <= len(tool.description) <= 512:
                self._invalid("invalid_tool_description", "tool descriptions must be bounded")
            validate_schema(tool.input_schema)

    def _normalize_generation(
        self,
        request: GenerationRequest,
        identity: ModelIdentity,
        result: ProviderGenerationResult,
        started: float,
    ) -> GenerationResponse:
        if not isinstance(result, ProviderGenerationResult) or not isinstance(result.text, str):
            self._provider_contract("generation_result_invalid")
        usage_values = (result.prompt_tokens, result.output_tokens)
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in usage_values
        ):
            self._provider_contract("usage_invalid")
        structured_value: Any | None = None
        proposals: tuple[ToolProposal, ...] = ()
        if request.capability is Capability.STRUCTURED_OUTPUT:
            assert request.structured_schema is not None
            try:
                structured_value = json.loads(result.text)
            except (TypeError, ValueError) as exc:
                raise ModelGatewayError(
                    GatewayErrorCategory.STRUCTURED_OUTPUT_INVALID,
                    "structured_output_invalid",
                    "the provider returned invalid structured output",
                ) from exc
            validate_structured_value(structured_value, request.structured_schema)
        elif request.capability is Capability.TOOL_CALL_PROPOSAL:
            proposals = self._normalize_tool_calls(result, request.tools)
        elif not result.text.strip():
            self._provider_contract("empty_generation_text")
        if not isinstance(result.finish_reason, str):
            self._provider_contract("finish_reason_invalid")
        return GenerationResponse(
            request_id=request.request_id,
            model=identity,
            text=result.text,
            structured_value=structured_value,
            tool_proposals=proposals,
            usage=Usage(
                prompt_tokens=result.prompt_tokens,
                output_tokens=result.output_tokens,
                total_tokens=result.prompt_tokens + result.output_tokens,
            ),
            finish_reason=result.finish_reason,
            latency_seconds=max(0.0, self._clock() - started),
        )

    def _normalize_tool_calls(
        self,
        result: ProviderGenerationResult,
        tools: tuple[ToolDefinition, ...],
    ) -> tuple[ToolProposal, ...]:
        definitions = {tool.name: tool for tool in tools}
        proposals: list[ToolProposal] = []
        if len(result.tool_calls) > len(tools):
            self._provider_contract("tool_call_count_invalid")
        for call in result.tool_calls:
            definition = definitions.get(call.name)
            if definition is None or not isinstance(call.arguments, Mapping):
                self._provider_contract("tool_call_invalid")
            try:
                validate_structured_value(call.arguments, definition.input_schema)
            except ModelGatewayError as exc:
                raise ModelGatewayError(
                    GatewayErrorCategory.PROVIDER_CONTRACT_VIOLATION,
                    "tool_call_arguments_invalid",
                    "provider tool proposal arguments violated the declared schema",
                ) from exc
            proposals.append(ToolProposal(name=call.name, arguments=dict(call.arguments)))
        return tuple(proposals)

    def _normalize_vectors(
        self, identity: ModelIdentity, result: ProviderEmbeddingResult
    ) -> tuple[tuple[float, ...], ...]:
        if not isinstance(result, ProviderEmbeddingResult):
            self._provider_contract("embedding_result_invalid")
        dimension = identity.embedding_dimension
        assert dimension is not None
        normalized: list[tuple[float, ...]] = []
        for vector in result.vectors:
            if len(vector) != dimension:
                self._provider_contract("embedding_dimension_invalid")
            values: list[float] = []
            for value in vector:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    self._provider_contract("embedding_value_invalid")
                numeric = float(value)
                if not math.isfinite(numeric):
                    self._provider_contract("embedding_value_non_finite")
                values.append(numeric)
            normalized.append(tuple(values))
        if not normalized:
            self._provider_contract("embedding_count_invalid")
        return tuple(normalized)

    def _model_presence(
        self, expected: ModelIdentity, inventory: tuple[ProviderModel, ...]
    ) -> ModelPresence:
        actual = next((item for item in inventory if item.model_id == expected.model_id), None)
        return ModelPresence(
            model_id=expected.model_id,
            present=actual is not None,
            identity_matches=actual is not None and actual.digest == expected.digest,
        )

    def _optional_health(
        self,
    ) -> tuple[tuple[ModelPresence, ...], Availability, HealthReason, str | None]:
        provider = self._providers.get(Provider.LLAMA_CPP)
        if provider is None or not self.settings.llama_cpp_enabled:
            return (
                self._missing_optional_models(),
                Availability.OFFLINE,
                HealthReason.MODEL_MISSING,
                None,
            )
        try:
            version = provider.version(timeout_seconds=self.settings.health_timeout_seconds)
            inventory = tuple(
                provider.inventory(timeout_seconds=self.settings.health_timeout_seconds)
            )
        except ProviderTimeoutError:
            return (
                self._missing_optional_models(),
                Availability.OFFLINE,
                HealthReason.PROVIDER_TIMEOUT,
                None,
            )
        except (ProviderOfflineError, ProviderTransientError):
            return (
                self._missing_optional_models(),
                Availability.OFFLINE,
                HealthReason.PROVIDER_UNREACHABLE,
                None,
            )
        except (ProviderContractError, ProviderRequestError):
            return (
                self._missing_optional_models(),
                Availability.DEGRADED,
                HealthReason.PROVIDER_CONTRACT_VIOLATION,
                None,
            )
        expected = self.settings.expected_llama_cpp_build
        presence = tuple(self._model_presence(model, inventory) for model in OPTIONAL_MODELS)
        if version != expected:
            return presence, Availability.DEGRADED, HealthReason.PROVIDER_VERSION_MISMATCH, version
        if any(not item.present for item in presence):
            return presence, Availability.OFFLINE, HealthReason.MODEL_MISSING, version
        if any(not item.identity_matches for item in presence):
            return presence, Availability.DEGRADED, HealthReason.MODEL_IDENTITY_MISMATCH, version
        return presence, Availability.AVAILABLE, HealthReason.READY, version

    @staticmethod
    def _missing_optional_models() -> tuple[ModelPresence, ...]:
        return tuple(ModelPresence(model.model_id, False, False) for model in OPTIONAL_MODELS)

    def _health_snapshot(
        self,
        started: float,
        availability: Availability,
        reason: HealthReason,
        required_models: tuple[ModelPresence, ...],
        provider_version: str | None = None,
        *,
        optional_models: tuple[ModelPresence, ...] = (),
        optional_availability: Availability = Availability.OFFLINE,
        optional_reason: HealthReason = HealthReason.MODEL_MISSING,
        optional_provider_version: str | None = None,
    ) -> HealthSnapshot:
        return HealthSnapshot(
            provider=Provider.OLLAMA,
            availability=availability,
            observed_at=datetime.now(UTC),
            latency_seconds=max(0.0, self._clock() - started),
            required_models=required_models,
            reason=reason,
            provider_version=provider_version,
            optional_models=optional_models,
            optional_availability=optional_availability,
            optional_reason=optional_reason,
            optional_provider_version=optional_provider_version,
        )

    def _circuit_for(self, identity: ModelIdentity) -> CircuitBreaker:
        key = (identity.provider, identity.model_id)
        if key not in self._circuits:
            self._circuits[key] = self._new_circuit(self._clock)
        return self._circuits[key]

    def _new_circuit(self, clock: Callable[[], float]) -> CircuitBreaker:
        return CircuitBreaker(
            failure_threshold=self.settings.circuit_failure_threshold,
            cooldown_seconds=self.settings.circuit_cooldown_seconds,
            clock=clock,
        )

    @staticmethod
    def _bounded_timeout(value: object, *, default: float, maximum: float) -> float:
        timeout = default if value is None else value
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 0 < timeout <= maximum
        ):
            raise ModelGatewayError(
                GatewayErrorCategory.INVALID_REQUEST,
                "invalid_timeout",
                "request timeout is outside the bounded operation limit",
            )
        return float(timeout)

    @staticmethod
    def _invalid(reason: str, message: str) -> Never:
        raise ModelGatewayError(GatewayErrorCategory.INVALID_REQUEST, reason, message)

    @staticmethod
    def _provider_contract(reason: str) -> Never:
        raise ModelGatewayError(
            GatewayErrorCategory.PROVIDER_CONTRACT_VIOLATION,
            reason,
            "the local provider response violated the gateway contract",
        )


__all__ = ["ModelGateway"]
