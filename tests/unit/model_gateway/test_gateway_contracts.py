from __future__ import annotations

import math

import pytest

from personal_ai_os.model_gateway import (
    BGE_M3,
    QWEN_4B,
    Capability,
    EmbeddingRequest,
    GatewayErrorCategory,
    GenerationRequest,
    ImageInput,
    Message,
    MessageRole,
    ModelGateway,
    ModelGatewayError,
    ToolDefinition,
)
from personal_ai_os.model_gateway.contracts import (
    ProviderEmbeddingResult,
    ProviderGenerationResult,
    ProviderModel,
    ProviderToolCall,
)
from personal_ai_os.model_gateway.provider import ProviderContractError, ProviderRequestError
from tests.unit.model_gateway.fakes import FakeProvider, finite_vectors


def generation_request(**changes: object) -> GenerationRequest:
    values: dict[str, object] = {
        "request_id": "phase-05a-request",
        "capability": Capability.GENERATION,
        "messages": (Message(MessageRole.USER, "Synthetic bounded prompt"),),
        "context_tokens": 4096,
        "max_output_tokens": 128,
    }
    values.update(changes)
    return GenerationRequest(**values)  # type: ignore[arg-type]


def test_generation_response_is_provider_neutral_and_attaches_exact_identity() -> None:
    provider = FakeProvider()
    response = ModelGateway(provider).generate(generation_request())
    assert response.model is QWEN_4B
    assert response.text == "synthetic response"
    assert response.usage.total_tokens == 6
    assert response.finish_reason == "stop"
    assert provider.inventory_calls == 1
    assert provider.generation_calls == 1


@pytest.mark.parametrize(
    ("context", "output"),
    [(4096, 256), (8192, 32), (16384, 32)],
)
def test_accepted_practical_context_budgets_reach_transport(context: int, output: int) -> None:
    provider = FakeProvider()
    ModelGateway(provider).generate(
        generation_request(context_tokens=context, max_output_tokens=output)
    )
    assert provider.generation_calls == 1


@pytest.mark.parametrize(
    ("context", "output"),
    [(32768, 32), (-1, 1), (4096, 0), (4096, -1), (4096, 257), (8192, 33)],
)
def test_invalid_budgets_fail_before_provider_transport(context: int, output: int) -> None:
    provider = FakeProvider()
    with pytest.raises(ModelGatewayError) as exc_info:
        ModelGateway(provider).generate(
            generation_request(context_tokens=context, max_output_tokens=output)
        )
    assert exc_info.value.category is GatewayErrorCategory.INVALID_REQUEST
    assert provider.inventory_calls == 0
    assert provider.generation_calls == 0


def test_request_limits_fail_before_transport() -> None:
    provider = FakeProvider()
    gateway = ModelGateway(provider)
    with pytest.raises(ModelGatewayError):
        gateway.generate(generation_request(messages=()))
    with pytest.raises(ModelGatewayError):
        gateway.generate(generation_request(messages=(Message(MessageRole.USER, "x" * 65_537),)))
    with pytest.raises(ModelGatewayError):
        gateway.generate(generation_request(timeout_seconds=61.0))
    assert provider.inventory_calls == 0
    assert provider.generation_calls == 0


def test_valid_structured_output_is_parsed_and_validated_once() -> None:
    provider = FakeProvider()
    provider.generation_result = ProviderGenerationResult(
        text='{"status":"ok"}', finish_reason="stop"
    )
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string", "enum": ["ok"]}},
        "required": ["status"],
        "additionalProperties": False,
    }
    response = ModelGateway(provider).generate(
        generation_request(
            capability=Capability.STRUCTURED_OUTPUT,
            structured_schema=schema,
        )
    )
    assert response.structured_value == {"status": "ok"}
    assert provider.generation_calls == 1


@pytest.mark.parametrize("text", ["not json", '{"status":"wrong"}', '{"extra":true}'])
def test_invalid_structured_output_is_typed_and_not_retried(text: str) -> None:
    provider = FakeProvider()
    provider.generation_result = ProviderGenerationResult(text=text, finish_reason="stop")
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string", "enum": ["ok"]}},
        "required": ["status"],
        "additionalProperties": False,
    }
    with pytest.raises(ModelGatewayError) as exc_info:
        ModelGateway(provider).generate(
            generation_request(
                capability=Capability.STRUCTURED_OUTPUT,
                structured_schema=schema,
            )
        )
    assert exc_info.value.category is GatewayErrorCategory.STRUCTURED_OUTPUT_INVALID
    assert provider.generation_calls == 1


def test_tool_call_is_normalized_as_data_and_never_executed() -> None:
    provider = FakeProvider()
    executions = 0
    provider.generation_result = ProviderGenerationResult(
        text="",
        finish_reason="stop",
        tool_calls=(ProviderToolCall(name="set_scene", arguments={"name": "focus"}),),
    )
    tool = ToolDefinition(
        name="set_scene",
        description="Propose a synthetic room scene.",
        input_schema={
            "type": "object",
            "properties": {"name": {"type": "string", "maxLength": 32}},
            "required": ["name"],
            "additionalProperties": False,
        },
    )
    response = ModelGateway(provider).generate(
        generation_request(capability=Capability.TOOL_CALL_PROPOSAL, tools=(tool,))
    )
    assert response.tool_proposals[0].name == "set_scene"
    assert response.tool_proposals[0].arguments == {"name": "focus"}
    assert executions == 0


def test_vision_forwards_only_explicit_bytes_and_never_fetches_a_url() -> None:
    provider = FakeProvider()
    image = ImageInput(media_type="image/png", data=b"synthetic-png-bytes")
    response = ModelGateway(provider).generate(
        generation_request(capability=Capability.VISION, images=(image,))
    )
    assert response.model is QWEN_4B
    assert provider.last_generation is not None
    assert provider.last_generation.images == (image,)
    assert not hasattr(image, "url")


def test_vision_requires_explicit_bounded_supported_image_bytes() -> None:
    provider = FakeProvider()
    gateway = ModelGateway(provider)
    with pytest.raises(ModelGatewayError):
        gateway.generate(generation_request(capability=Capability.VISION))
    with pytest.raises(ModelGatewayError):
        gateway.generate(
            generation_request(
                capability=Capability.VISION,
                images=(ImageInput(media_type="image/svg+xml", data=b"<svg/>"),),
            )
        )
    assert provider.generation_calls == 0


def test_embedding_single_and_batch_are_finite_1024_dimensional() -> None:
    provider = FakeProvider()
    provider.embedding_result = ProviderEmbeddingResult(vectors=finite_vectors(2))
    response = ModelGateway(provider).embed(
        EmbeddingRequest(request_id="phase-05a-embed", texts=("one", "two"))
    )
    assert response.model is BGE_M3
    assert response.count == 2
    assert response.dimension == 1024
    assert all(len(vector) == 1024 for vector in response.vectors)
    assert all(math.isfinite(value) for vector in response.vectors for value in vector)


@pytest.mark.parametrize(
    "vectors",
    [
        ((0.0,) * 1023,),
        ((float("nan"),) + (0.0,) * 1023,),
        ((float("inf"),) + (0.0,) * 1023,),
        finite_vectors(2),
    ],
)
def test_invalid_embedding_shape_values_or_count_fail_closed(
    vectors: tuple[tuple[float, ...], ...],
) -> None:
    provider = FakeProvider()
    provider.embedding_result = ProviderEmbeddingResult(vectors=vectors)
    with pytest.raises(ModelGatewayError) as exc_info:
        ModelGateway(provider).embed(
            EmbeddingRequest(request_id="phase-05a-embed-invalid", texts=("one",))
        )
    assert exc_info.value.category is GatewayErrorCategory.PROVIDER_CONTRACT_VIOLATION
    assert provider.embedding_calls == 1


def test_missing_model_and_digest_mismatch_are_distinct_fail_closed_errors() -> None:
    missing = FakeProvider()
    missing.models = tuple(model for model in missing.models if model.model_id != QWEN_4B.model_id)
    with pytest.raises(ModelGatewayError) as missing_error:
        ModelGateway(missing).generate(generation_request())
    assert missing_error.value.reason_code == "model_missing"
    assert missing.generation_calls == 0

    mismatch = FakeProvider()
    mismatch.models = tuple(
        ProviderModel(model.model_id, "sha256:" + "0" * 64)
        if model.model_id == QWEN_4B.model_id
        else model
        for model in mismatch.models
    )
    with pytest.raises(ModelGatewayError) as mismatch_error:
        ModelGateway(mismatch).generate(generation_request())
    assert mismatch_error.value.category is GatewayErrorCategory.MODEL_IDENTITY_MISMATCH
    assert mismatch.generation_calls == 0


def test_embedding_model_missing_and_digest_mismatch_never_call_embed() -> None:
    missing = FakeProvider()
    missing.models = tuple(model for model in missing.models if model.model_id != BGE_M3.model_id)
    with pytest.raises(ModelGatewayError) as missing_error:
        ModelGateway(missing).embed(
            EmbeddingRequest(request_id="phase-05a-bge-missing", texts=("synthetic",))
        )
    assert missing_error.value.reason_code == "model_missing"
    assert missing.embedding_calls == 0

    mismatch = FakeProvider()
    mismatch.models = tuple(
        ProviderModel(model.model_id, "sha256:" + "0" * 64)
        if model.model_id == BGE_M3.model_id
        else model
        for model in mismatch.models
    )
    with pytest.raises(ModelGatewayError) as mismatch_error:
        ModelGateway(mismatch).embed(
            EmbeddingRequest(request_id="phase-05a-bge-mismatch", texts=("synthetic",))
        )
    assert mismatch_error.value.category is GatewayErrorCategory.MODEL_IDENTITY_MISMATCH
    assert mismatch.embedding_calls == 0


@pytest.mark.parametrize("failure", [ProviderRequestError("raw"), ProviderContractError("raw")])
def test_deterministic_provider_failures_are_not_retried_or_leaked(failure: Exception) -> None:
    provider = FakeProvider()
    provider.generation_failures = [failure]
    with pytest.raises(ModelGatewayError) as exc_info:
        ModelGateway(provider).generate(generation_request())
    assert exc_info.value.category is GatewayErrorCategory.PROVIDER_CONTRACT_VIOLATION
    assert provider.generation_calls == 1
    assert "raw" not in str(exc_info.value)


def test_unexpected_provider_failure_is_sanitized_and_not_retried() -> None:
    provider = FakeProvider()
    provider.generation_failures = [RuntimeError("raw private provider detail")]
    with pytest.raises(ModelGatewayError) as exc_info:
        ModelGateway(provider).generate(generation_request())
    assert exc_info.value.category is GatewayErrorCategory.PROVIDER_CONTRACT_VIOLATION
    assert provider.generation_calls == 1
    assert "raw private" not in str(exc_info.value)
