"""Run bounded real Phase 5B gateway acceptance without retaining model content."""

from __future__ import annotations

import argparse
import json
import math
import socket
import threading
import time
from pathlib import Path
from typing import Any

from personal_ai_os.model_gateway import (
    Availability,
    Capability,
    EmbeddingRequest,
    GatewayErrorCategory,
    GatewaySettings,
    GenerationRequest,
    Message,
    MessageRole,
    ModelGateway,
    ModelGatewayError,
    OllamaProvider,
    ToolDefinition,
)
from personal_ai_os.model_gateway.resilience import CircuitState

ENDPOINT = "http://127.0.0.1:11434"


def gateway(settings: GatewaySettings | None = None) -> ModelGateway:
    return ModelGateway(OllamaProvider(ENDPOINT), settings or GatewaySettings())


def circuit_state(instance: ModelGateway) -> CircuitState:
    """Read mutable circuit state without static narrowing across real calls."""

    return instance.circuit.state


def generation_request(request_id: str, *, tools: bool = False) -> GenerationRequest:
    definitions: tuple[ToolDefinition, ...] = ()
    capability = Capability.GENERATION
    prompt = "Reply with one short synthetic status word."
    if tools:
        capability = Capability.TOOL_CALL_PROPOSAL
        prompt = "Propose set_scene with name focus. Do not perform any action."
        definitions = (
            ToolDefinition(
                name="set_scene",
                description="Propose a synthetic scene name without executing it.",
                input_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string", "maxLength": 32}},
                    "required": ["name"],
                    "additionalProperties": False,
                },
            ),
        )
    return GenerationRequest(
        request_id=request_id,
        capability=capability,
        messages=(Message(MessageRole.USER, prompt),),
        max_output_tokens=16,
        tools=definitions,
    )


def listener_present() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=0.25):
            return True
    except OSError:
        return False


def wait_for_listener(expected: bool, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if listener_present() is expected:
            return
        time.sleep(0.2)
    raise RuntimeError("bounded listener transition did not occur")


def health_result(expected_version: str) -> dict[str, Any]:
    snapshot = gateway(GatewaySettings(expected_ollama_version=expected_version)).health()
    return {
        "availability": snapshot.availability.value,
        "reason": snapshot.reason.value,
        "provider_version": snapshot.provider_version,
    }


def smoke_result() -> dict[str, Any]:
    instance = gateway()
    health = instance.health()
    if health.availability is not Availability.AVAILABLE:
        raise RuntimeError("gateway is not available for smoke acceptance")
    generated = instance.generate(generation_request("phase-05b-generation"))
    embedded = instance.embed(
        EmbeddingRequest(request_id="phase-05b-embedding", texts=("synthetic local text",))
    )
    proposed = instance.generate(generation_request("phase-05b-tool", tools=True))
    if embedded.count != 1 or embedded.dimension != 1024:
        raise RuntimeError("embedding shape does not match the accepted identity")
    if not all(math.isfinite(value) for value in embedded.vectors[0]):
        raise RuntimeError("embedding contains a non-finite value")
    if not proposed.tool_proposals:
        raise RuntimeError("the bounded data-only tool proposal was not returned")
    return {
        "health": "available",
        "generation": {
            "success": True,
            "model": generated.model.model_id,
            "digest": generated.model.digest,
            "latency_ms": round(generated.latency_seconds * 1000, 3),
            "prompt_tokens": generated.usage.prompt_tokens,
            "output_tokens": generated.usage.output_tokens,
            "finish_reason": generated.finish_reason,
        },
        "embedding": {
            "success": True,
            "model": embedded.model.model_id,
            "digest": embedded.model.digest,
            "count": embedded.count,
            "dimension": embedded.dimension,
            "finite": True,
            "latency_ms": round(embedded.latency_seconds * 1000, 3),
        },
        "tool_proposal": {
            "returned_as_data": True,
            "proposal_count": len(proposed.tool_proposals),
            "execution_authority": False,
        },
    }


def offline_result() -> dict[str, Any]:
    instance = gateway()
    snapshot = instance.health()
    if snapshot.availability is not Availability.OFFLINE:
        raise RuntimeError("gateway did not report offline")
    try:
        instance.generate(generation_request("phase-05b-offline"))
    except ModelGatewayError as exc:
        if exc.category is not GatewayErrorCategory.PROVIDER_UNAVAILABLE:
            raise
        return {
            "health": "offline",
            "generation_category": exc.category.value,
            "attempts": exc.attempts,
            "cloud_fallback": False,
        }
    raise RuntimeError("offline generation unexpectedly succeeded")


def concurrency_result() -> dict[str, Any]:
    instance = gateway(GatewaySettings(concurrency_wait_seconds=0.1))
    first: dict[str, Any] = {}

    def run_first() -> None:
        try:
            response = instance.generate(generation_request("phase-05b-concurrency-first"))
            first["success"] = True
            first["latency_ms"] = round(response.latency_seconds * 1000, 3)
        except BaseException as exc:  # captured for deterministic parent-thread handling
            first["error"] = type(exc).__name__

    thread = threading.Thread(target=run_first)
    thread.start()
    time.sleep(0.05)
    second_category = "unexpected_success"
    try:
        instance.generate(generation_request("phase-05b-concurrency-second"))
    except ModelGatewayError as exc:
        second_category = exc.category.value
    thread.join(timeout=65)
    if thread.is_alive() or first.get("success") is not True:
        raise RuntimeError("first bounded concurrency request did not complete")
    if second_category != GatewayErrorCategory.BUSY.value:
        raise RuntimeError("second bounded concurrency request was not typed busy")
    return {
        "first_success": True,
        "first_latency_ms": first["latency_ms"],
        "second_category": second_category,
        "callers": 2,
    }


def circuit_result(control_dir: Path) -> dict[str, Any]:
    control_dir.mkdir(parents=True, exist_ok=True)
    for name in ("ready_stop", "ready_restore"):
        (control_dir / name).unlink(missing_ok=True)
    instance = gateway(GatewaySettings(circuit_cooldown_seconds=2.0, retry_backoff_seconds=0.05))
    if instance.health().availability is not Availability.AVAILABLE:
        raise RuntimeError("circuit acceptance did not start available")
    (control_dir / "ready_stop").write_text("ready\n", encoding="utf-8")
    wait_for_listener(False)
    try:
        instance.generate(generation_request("phase-05b-circuit-open"))
    except ModelGatewayError as exc:
        first_category = exc.category.value
        first_attempts = exc.attempts
    else:
        raise RuntimeError("transport disruption did not fail generation")
    if circuit_state(instance) is not CircuitState.OPEN or first_attempts != 2:
        raise RuntimeError("bounded failures did not open the circuit")
    try:
        instance.generate(generation_request("phase-05b-circuit-fast"))
    except ModelGatewayError as exc:
        fast_reason = exc.reason_code
        fast_attempts = exc.attempts
    else:
        raise RuntimeError("open circuit did not fail fast")
    (control_dir / "ready_restore").write_text("ready\n", encoding="utf-8")
    wait_for_listener(True)
    time.sleep(2.1)
    probe = instance.generate(generation_request("phase-05b-half-open"))
    subsequent = instance.generate(generation_request("phase-05b-closed"))
    if circuit_state(instance) is not CircuitState.CLOSED:
        raise RuntimeError("successful half-open probe did not close the circuit")
    return {
        "initial": "available",
        "failure_category": first_category,
        "failure_attempts": first_attempts,
        "open_fast_reason": fast_reason,
        "open_fast_attempts": fast_attempts,
        "half_open_probe_success": bool(probe.text),
        "closed_subsequent_success": bool(subsequent.text),
        "final_state": circuit_state(instance).value,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode", choices=("health", "degraded", "smoke", "offline", "concurrency", "circuit")
    )
    parser.add_argument("--control-dir", type=Path, default=Path("/tmp/bmo-phase5b-circuit"))
    args = parser.parse_args()
    if args.mode == "health":
        result = health_result("0.32.5")
    elif args.mode == "degraded":
        result = health_result("0.0.0-phase-05b-test")
    elif args.mode == "smoke":
        result = smoke_result()
    elif args.mode == "offline":
        result = offline_result()
    elif args.mode == "concurrency":
        result = concurrency_result()
    else:
        result = circuit_result(args.control_dir)
    print(json.dumps({"mode": args.mode, "result": result}, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
