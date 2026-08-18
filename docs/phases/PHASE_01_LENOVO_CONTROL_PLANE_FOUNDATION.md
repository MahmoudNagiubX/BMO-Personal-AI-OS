# Phase 1 — Lenovo/VENOM control-plane foundation

**Status:** IN PROGRESS — repository foundation ready for independent review

## Goal

Record the verified VENOM physical foundation in the canonical repository and
prepare bounded, inspectable evidence and runbooks for the remaining Lenovo
Safety Gate. This phase continues from the owner-provided physical handoff; it
does not reinstall Ubuntu or modify the host.

## Runtime identity and topology

- Runtime identity: `VENOM`
- Hostname: `venom-server`
- Linux user: `venom`
- Control plane candidate: Lenovo G450, Ubuntu Server 24.04.4 LTS AMD64,
  headless
- Heavy AI and Windows plane: ASUS TUF
- Source-of-truth workflow: ASUS TUF -> GitHub -> reviewed commit -> Lenovo SSH

The manual `~/venom/core/brain/main.py` FastAPI service is proof-of-life only.
It is not the product backend. No second backend may be built under that
workspace; future deployed code must come from an exact reviewed commit under
`src/personal_ai_os/`.

## Verified physical handoff incorporated

The owner-provided `VENOM_SERVER_FOUNDATION_COMPLETE_HANDOFF` is recorded in
the sanitized evidence file at
`infrastructure/home_server/evidence/venom_foundation_handoff.json`:

- Ubuntu Server 24.04.4 LTS, x86_64, hostname `venom-server`, user `venom`.
- Lenovo G450 with Intel Core 2 Duo T6500, 2 cores, and approximately 4 GiB
  RAM.
- `/dev/sda`, Seagate ST9320325AS, approximately 298 GiB.
- SMART supported and clean; SMART short test passed; reallocated, pending,
  and offline-uncorrectable sectors are all zero.
- OpenSSH enabled and reachable; UFW enabled with SSH allowed.
- Manual `~/venom` Python/FastAPI/Uvicorn proof-of-life returned
  `VENOM online / brain initialized`.

This record remains historical handoff evidence. The current physical-gate
session is recorded separately in
`infrastructure/home_server/evidence/venom_physical_gate.json`; it verified
the live identity, Ethernet path, thermal peak, bounded memory result, key
login, and owner visual safety confirmations without claiming the final gate.

## Remaining Lenovo Safety Gate work

The physical gate remains **IN PROGRESS**. The current session verified:

- Ethernet primary route at `192.162.1.21/24`, 100 Mb/s full duplex;
- CPU peak evidence of 62 C / 61 C under the one permitted 30-second test;
- bounded 1 GiB memory evidence with zero swap use;
- dedicated Ed25519 key login and no running FastAPI proof service;
- owner visual confirmation of no battery, no case distortion, and normal fan.

The following remain follow-ups requiring privileged or real-time evidence:

- wired Ethernet link, route, speed, and duplex;
- memory, swap, DIMM, filesystem, LVM, and free-space baseline;
- battery/power continuity because no battery is installed;
- SSH root-login hardening and private-LAN UFW scoping;
- system baseline, resource admission, and bounded log rotation;
- off-device backup and a real small restore;
- reboot/network/SSH/UFW recovery;
- system-level 15-minute monitoring, off-device backup/restore, reboot recovery,
  and continuous 24-hour then 7-day stability gates.

Do not claim `PHASE 1 / LENOVO SAFETY GATE — PASS` until every item passes.
Do not run uncontrolled stress, resize LVM, set final swap blindly, open
public ports, or admit the production stack from this repository task.

## Repository scope

This phase adds the sanitized handoff, current physical-gate evidence and
validator, bounded thermal/memory runners, scalar stability monitor and timer
units, prerequisite checker, host infrastructure directory, and runbooks. It
updates current status and verified hardware facts while preserving ADR
history, the canonical backend, the ASUS TUF/GitHub/SSH workflow, and the
deferred Qwen3.5 9B decision.

Phase 5B, physical deployment, model changes, database changes, and a full
BMO-to-VENOM rename are outside this phase.

## Rollback

Rollback is a normal revert of the repository documentation, evidence, tests,
and tooling commit. The added checker is read-only and has no host-side
rollback action. The manual proof-of-life workspace remains untouched.
