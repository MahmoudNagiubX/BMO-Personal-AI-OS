# ADR-0003 — Split always-on control from heavy AI compute

- **Status:** Superseded
- **Date:** 2026-07-31
- **Deciders:** Mahmoud
- **Supersedes:** None
- **Superseded by:** ADR-0005

> This ADR is retained as historical architecture evidence. ADR-0005 later removed the Lenovo from the active topology; ADR-0007 supersedes ADR-0005 and restores the Lenovo as a temporary lightweight host without reactivating this historical ADR.

## Context

The Lenovo G450 can remain on continuously but has a Core 2 Duo, 4 GB RAM, and no useful AI GPU. The ASUS TUF has an RTX 4050 and 16 GB RAM but should not be required to stay on for room automation and core deterministic services.

## Decision

Use the Ubuntu Server Lenovo as the always-on control plane and home edge hub. Use the Windows ASUS TUF as the heavy compute and Windows execution node.

The Lenovo owns core API coordination, identity, approvals, scheduler, MQTT, Home Assistant, database subject to the health gate, notifications, and Wake-on-LAN. The TUF owns Ollama, Qwen models, BGE-M3, heavy speech/vision, browser automation, and the Windows satellite.

## Rationale

This used the hardware available when the decision was accepted, preserved 24/7 deterministic functionality, and avoided pretending the Lenovo could run a strong local model.

## Consequences

### Positive

- Core automations survive TUF shutdown.
- Heavy inference uses the GPU.
- No cloud model is required.

### Negative / trade-offs

- Full natural conversation may be unavailable while the TUF is offline.
- Network discovery, authentication, health routing, and Wake-on-LAN are required.
- The Lenovo resource ceiling is too restrictive for the preferred long-term control plane.

## Security and privacy impact

All cross-device traffic requires authenticated private-network communication and scoped device identities. Internal services must not be exposed publicly.

## Migration and rollback

ADR-0005 superseded this host selection while preserving the control/compute split and stable service interfaces. ADR-0007 now governs the temporary Lenovo host. This historical decision and branch must not be used to authorize new Lenovo work.

## Validation

Historical validation was defined as Phase 1 hardware and network health gates, Phase 4 model benchmarks, TUF-offline integration tests, and reboot/recovery tests. Current host validation is defined by ADR-0007.
