# Implementation Status

> This file records verified repository state, owner-approved architecture, and the current sanitized VENOM physical-gate evidence. The Lenovo 24-hour and seven-day observation windows remain real-time evidence, not manually asserted success states.

- **Plan baseline:** 2.0 — 2026-08-20
- **Current phase boundary:** Phase 5B, Phase 6, Phase 7, Phase 8, optional Phase 8.5, and Phase 9 are merged. Persistent Phase 6/7/8 Core API authority, private PostgreSQL/pgvector, and verified off-device backups were deployed on VENOM under explicit owner authorization. The Phase 9 physical tool gate on the ASUS TUF was executed end-to-end and passed all physical acceptance criteria. VENOM was cleanly restored to the accepted production baseline `24297a9c8ce8ce8d386874949aa3d87e0881d9cc` (migration `20260820_0005`). Phase 10 JARVIS Voice Core is owner-authorized and begins on the new branch; Phase 11 room/multi-device voice remains `NOT_STARTED`.
- **Current state:** PR #9 is merged and Phase 5A is closed. The Phase 1 Lenovo/VENOM repository foundation is merged. Phase 6 identity/device enrollment is merged and verified live on VENOM. Phase 7 text-first conversation and clients are implemented and merged, and verified live on VENOM over the reverse tunnel. Phase 8 tool permissions, exact-owner approvals, and audit trails are verified live on VENOM. Phase 9 Windows satellite outbound connection, allowlist execution, telemetry, file search, app open, project open, volume control, consequential workflow approval/verification, cancellation, and security boundaries were tested live on the ASUS TUF against VENOM.
- **Current evidence:** Phase 1 physical evidence remains in `infrastructure/home_server/evidence/venom_physical_gate.json`. Sanitized Phase 9 repository and physical acceptance evidence is recorded in `docs/phase_reports/evidence/PHASE_09_WINDOWS_SATELLITE.json`.
 **Current branch target:** `phase-10/jarvis-voice-core`; the active wake design is the official openWakeWord Hey Jarvis candidate plus the owner-specific custom verifier behind a manifest/SHA-verified local profile. The profile is not committed and owner enrollment remains required before physical acceptance. The prior faster-whisper wake verifier and backend comparison results remain historical; faster-whisper remains conversational STT. Right-Ctrl/PTT activation, pre-roll, Smart Turn, barge-in, privacy, and Core authority remain unchanged.
- **Phase 10 v2 implementation evidence:** commit `c46bddba7e6f3350ba1e86d6d61959855008b85e` records the earlier non-owner MFCC viability benchmark. The follow-up comparison runner at `a7ae0f83f9827ce6e62b10ceee8f9cf8244086e8` tested 48 positives and 248 negatives: BMO 37/48 recall with 15/248 false activations; WakeForge 48/48 recall with 248/248 false activations at its fixed threshold. The two-stage cascade runner at `b5dcd69bbd235d63f8ae0c66a2f0843428a8977c` tested 60 positives and 310 negatives with BMO→Whisper, WakeForge→Whisper, and VAD→Whisper control; each reached 56/60 (93.33%) recall with 0/310 false activations. The dedicated verifier implementation at `e9de3ead8b1deccf67e135ab0f84e02ee805ce30` verified the local CUDA runtime and tested pinned tiny.en/base.en/small.en models with 96.0% recall on base.en (ADR-0015). The pre-fix whole-utterance stateful artifact is historical/superseded; production-equivalent streaming evidence is `evidence/PHASE_10_STREAMING_WAKE_PATH.json` at implementation commit `beadb55f9d4221ffa3b876edfe4c38380cafc820` (ADR-0017). Exact-head GitHub CI remains an external governance check.
- **Phase 10 owner-verifier enrollment:** the first scalar-only owner attempt is retained truthfully in `evidence/PHASE_10_OWNER_VERIFIER.json`, but does not authorize production. The corrected local harness separates base invocation, final held-out acceptance, and temporal thresholds; keeps profiles provisional until calibration succeeds; disables regressive internal openWakeWord VAD; and retains no raw owner audio. Owner re-enrollment remains paused pending this corrected implementation's validation and exact-head CI.
- **Phase 10 owner-verifier extraction correction:** owner attempt 2 passed audio quality but exposed the pinned upstream positive-feature extraction default of `0.5` before artifact creation. The BMO-owned wrapper now uses the calibrated broad-corpus base invocation threshold for both positive preflight and feature extraction, adds bounded ambient pre-roll only in temporary training WAVs, and records scalar base scores. Physical acceptance remains unauthorized until the calibrated personalized software gates pass.
- **Phase 10 broad base-candidate calibration:** the production-capture-equivalent synthetic corpus measured 504 positives and 7,268 negatives. The selected explicit invocation threshold is `0.1959392`, yielding 502/504 candidate recall (`0.996`) with internal OpenWakeWord VAD disabled; the 1,084/7,268 candidate false-event rate remains a pre-verifier diagnostic, not a production wake claim.
- **Measured stability:** 24-hour `WAITING / WAIVED_AS_BLOCKING_PREREQUISITE / still monitoring`; seven-day `WAITING / WAIVED_AS_BLOCKING_PREREQUISITE / still monitoring`. These are not stability PASS states.
- **Later phases authorized:** ADR-0008 historically recorded Phase 5B as `AUTHORIZED_TO_START`. Phase 6, Phase 7, Phase 8, optional Phase 8.5, and Phase 9 are merged in repository history. Phase 10 JARVIS Voice Core v2 is owner-authorized; Picovoice/Porcupine and other paid wake-word services are rejected, all prior wake candidates remain historical evidence, ADR-0012 through ADR-0017 record superseded or historical bare-`Jarvis` evaluations, and ADR-0018 records the active exact `Hey Jarvis` migration and blocked software gate. Phase 11 room/multi-device voice is `NOT_STARTED` and is not authorized by this phase.
 **Hey Jarvis final audit:** ADR-0018 records the migration, ADR-0019 and ADR-0020 retain historical cleanup/reselection evidence, and ADR-0021 records the owner-specific verifier, local enrollment, digest binding, temporary-audio cleanup, and pending software gate. Phase 11 remains `NOT_STARTED`.

## Accepted topology

### Lenovo G450 — temporary lightweight always-on control plane

ADR-0007 is the active host decision. Owner-provided physical handoff facts are:

- Intel Core 2 Duo T6500, 2 cores, x86_64.
- Approximately 4 GB RAM.
- `/dev/sda`, Seagate ST9320325AS, approximately 298 GB.
- Physical RJ-45 Ethernet.
- No useful AI GPU and no local heavy inference.

The same handoff records Ubuntu Server 24.04.4 LTS, hostname `venom-server`,
Linux user `venom`, OpenSSH reachability, UFW enabled with SSH allowed, clean
SMART evidence, and the manual `~/venom` FastAPI proof-of-life. These facts do
not constitute completion of the physical Safety Gate.

The authorized closeout recovery installed and verified SMART tooling, denied
root SSH while retaining password recovery and key authentication, scoped UFW
to `192.162.1.0/24`, bounded journald, installed the durable root scalar
monitor, proved encrypted off-device backup and temporary restore, and verified
one controlled reboot. The preliminary marker and official markers at
`2026-08-18T22:28:46Z` and `2026-08-18T23:29:53Z` are preserved as superseded
history. The FINAL real-time stability marker began at `2026-08-19T00:11:05Z`
UTC with boot ID `0722b8e8-1c8c-4268-83f8-eeda51724308`. The new monitor records SMART sector
counters 5, 197, and 198 without serials or raw SMART output. The encrypted
backup is persistent outside Git on the ASUS TUF, and the effective lid policy
is `ignore` for lid, external power, and docked operation.

The real evaluator at `scripts/phase_01/evaluate_stability_gate.py` derives
WAITING_FOR_24H, WAITING_FOR_7D, BLOCKED, or PASS from the official marker and
sanitized monitor samples. At the 24-hour and seven-day boundaries it requires
leading, adjacent, and trailing timestamp gaps of at most 1,860 seconds, plus
75% minimum 15-minute coverage and zero SMART sector counters. Small stable
residual swap is allowed; only three consecutive samples at or above 256 MiB
block as sustained pressure. Malformed sample data returns `BLOCKED`; manually
edited status strings are never trusted.

The operating baseline is Ubuntu Server 24.04.4 LTS AMD64, headless, with no desktop GUI. Preserve Legacy BIOS/MBR compatibility in installation planning, but do not claim the exact firmware boot mode before inspection. DHCP is acceptable for initial installation; any fixed address or DHCP reservation follows network inspection. SSH is required after installation. Services remain private-LAN only, with no public port forwarding.

The Lenovo may provide the Core API and lightweight orchestration, identity/device registry, permissions and approvals, scheduler, audit/event coordination, Mosquitto MQTT, model gateway and ASUS TUF health routing, notifications, service discovery, and backup coordination. Home Assistant and PostgreSQL/pgvector remain conditional on measured safety, storage, RAM, and load acceptance. The Lenovo must not run Qwen3.5 4B, BGE-M3 inference, heavy STT/TTS, heavy vision/indexing, a local heavy LLM, or an unrestricted LLM shell.

Because the Lenovo has 4 GB RAM, installation remains minimal and headless. Configure swap only after disk and RAM inspection; admit Docker and services gradually from measured memory, disk, and load pressure. Require SMART monitoring, bounded logs, free-space thresholds, off-device backups, restore evidence, and staged stability gates. Do not add Redis, Kafka, Elasticsearch, Kubernetes, Prometheus, or Grafana without a later ADR and measured need.

### ASUS TUF — heavy compute and Windows execution plane

The ASUS TUF retains native Ollama, Qwen3.5 4B as the default primary generation/orchestration/vision model, BGE-M3 embeddings, the single-device JARVIS Voice Core, heavy speech/vision/indexing, the Windows satellite, isolated browser automation, development, benchmarking, and Codex work. ADR-0009 adds an optional text-only Qwen3.5-9B Heretic v2 llama.cpp provider on loopback port 11435; it is not a Phase 4 requirement, is never a silent fallback, and remains unavailable without making the accepted fast stack appear dead. When the TUF is unavailable, Lenovo-hosted deterministic functions must degrade honestly rather than making the full backend appear dead. Voice inference and audio capture remain on the TUF; no heavy STT/TTS runs on Lenovo.

### Desktop PC — future control-plane upgrade candidate

ADR-0005 and the owner-reported desktop hardware facts are preserved as historical evidence. The desktop PC is not the current deployment authority, active topology node, mandatory safety gate, or Phase 5B prerequisite. A future Lenovo-to-desktop migration requires a new owner-approved host-migration ADR and a separate safety gate.

## Historical branch boundary

- ADR-0003 remains historical and superseded by ADR-0005.
- ADR-0005 is superseded by ADR-0007.
- `phase-01/lenovo-foundation` remains unmerged audit history and must not be merged, rebased, force-pushed, rewritten, or reused.
- The new `phase-01/lenovo-control-plane-foundation` branch is the repository-side continuation from current `main`; physical Lenovo work remains separately owner-authorized.

## Verified sequencing state

- PR #7 merged into `main` at `caeb366af121ed3f2dca5239f34346a13f8a031a`.
- PR #8 merged into `main` at `a4a4cf78890c5efe98830a6ecc22757cf9f826f2`; Phase 4 is closed.
- PR #9 merged and closed into `main` at `7d0ec7aa957c5d3b33f4fc7818da0e5cc6382620`; Phase 5A is closed.
- PR #10 merged into `main` at `e8a2ddd6ecb4dac75b09fe6d96ec3071d270de41`; ADR-0007 is the accepted active architecture.
- PR #15 merged into `main` at `a3c698a9cc8dd7fbedd69fc1e3f73c134c6e41c2`; Phase 5B is closed.
- The accepted default stack is Qwen3.5 4B plus BGE-M3. The optional Qwen3.5-9B Heretic v2 llama.cpp identity is defined by ADR-0009 and is not required by Phase 4 or the fast path.
- The accepted sequence is **architecture update restoring Lenovo → Lenovo G450 Safety Gate → Lenovo Ubuntu Server foundation → Phase 5B deployment/integration acceptance → Phase 6 identity/device enrollment → Phase 7 → Phase 8 repository security platform → optional Phase 8.5 advanced-provider admission → Phase 9 Windows satellite → Phase 10 JARVIS Voice Core → Phase 11 room/multi-device voice**. Phase 10 is single-device TUF voice only; Phase 11 remains `NOT_STARTED`. The measured stability gates remain waiting under ADR-0008 and background monitoring remains active. Persistent Phase 6–8 Core API and PostgreSQL authority were deployed on VENOM under explicit owner authorization, the Phase 9 physical tool gate on the TUF was executed and verified, and VENOM was restored to the accepted baseline `24297a9c8ce8ce8d386874949aa3d87e0881d9cc` (migration `20260820_0005`).

## Verified Phase 2 and Phase 3 implementation state

- Phase 2 health, configuration, logging, SQLAlchemy/Alembic, PostgreSQL/pgvector Compose, and CI foundation are merged. GitHub CI is authoritative for the PostgreSQL path.
- Phase 3 pins OpenJarvis `1.0.0`, confines direct imports to the adapter, and verifies local-only request, bounded identifiers, trace redaction, contracts, and PostgreSQL integration. PR #5 is merged.

## Phase boundary

Phase 9 adds the repository-side authenticated outbound Windows satellite, strict local allowlist, fixed typed executors, secure current-user credential storage, cancellation/replay protection, and Phase 8-governed routing. Phase 10 adds only the local single-device JARVIS Voice Core on the TUF; it does not add room nodes, distributed microphones, public/LAN voice endpoints, heavy Lenovo compute, or direct model/tool authority. Phase 11 room/multi-device voice remains `NOT_STARTED`. Background Phase 1 monitoring remains actionable: SMART overall failure, any SMART counters 5/197/198 above zero, repeated thermal breach, root-filesystem pressure, unexpected reboot patterns, repeated failed units, or repeated Ethernet management-path loss pause deployment expansion and require reporting.
