# ADR-0003 — Split always-on control from heavy AI compute

- **Status:** Accepted
- **Date:** 2026-07-31
- **Deciders:** Mahmoud
- **Supersedes:** None
- **Superseded by:** None

## Context

The Lenovo G450 can remain on continuously but has a Core 2 Duo, 4 GB RAM, and no useful AI GPU. The ASUS TUF has an RTX 4050 and 16 GB RAM but should not be required to stay on for room automation and core deterministic services.

## Decision

Use the Ubuntu Server Lenovo as the always-on control plane and home edge hub. Use the Windows ASUS TUF as the heavy compute and Windows execution node.

The Lenovo owns core API coordination, identity, approvals, scheduler, MQTT, Home Assistant, database subject to the health gate, notifications, and Wake-on-LAN. The TUF owns Ollama, Qwen models, BGE-M3, heavy speech/vision, browser automation, and the Windows satellite.

## Rationale

This uses existing hardware efficiently, preserves 24/7 deterministic functionality, and avoids pretending the Lenovo can run a strong local model.

## Consequences

### Positive

- Core automations survive TUF shutdown.
- Heavy inference uses the GPU.
- No cloud model is required.

### Negative / trade-offs

- Full natural conversation may be unavailable while the TUF is offline.
- Network discovery, authentication, health routing, and Wake-on-LAN are required.

## Security and privacy impact

All cross-device traffic requires authenticated private-network communication and scoped device identities. Internal services must not be exposed publicly.

## Migration and rollback

Services may move to newer hardware later behind stable interfaces. The Lenovo must retain configuration and backup data; model services can be re-created on another compute node.

## Validation

Phase 1 hardware and network health gates, Phase 4 model benchmarks, TUF-offline integration tests, and reboot/recovery tests.
