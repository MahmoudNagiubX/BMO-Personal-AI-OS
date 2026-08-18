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

This record is historical evidence supplied by the owner for repository
reconciliation. No SSH connection or physical host action was performed in
this task.

## Remaining Lenovo Safety Gate work

The physical gate remains **INCOMPLETE**. The following require owner-run,
reviewed evidence on VENOM:

- wired Ethernet link, route, speed, and duplex;
- memory, swap, DIMM, filesystem, LVM, and free-space baseline;
- idle and bounded-load thermals, fan behavior, and battery/power behavior;
- SSH key-auth recovery and private-LAN UFW scoping;
- system baseline, resource admission, and bounded log rotation;
- off-device backup and a real small restore;
- reboot/network/SSH/UFW recovery;
- continuous 24-hour and then 7-day stability gates.

Do not claim `PHASE 1 / LENOVO SAFETY GATE — PASS` until every item passes.
Do not run uncontrolled stress, resize LVM, set final swap blindly, open
public ports, or admit the production stack from this repository task.

## Repository scope

This phase adds the sanitized handoff, evidence validator, read-only
prerequisite checker, host infrastructure directory, and human-executed
runbooks. It updates current status and verified hardware facts while
preserving ADR history, the canonical backend, the ASUS TUF/GitHub/SSH
workflow, and the deferred Qwen3.5 9B decision.

Phase 5B, physical deployment, model changes, database changes, and a full
BMO-to-VENOM rename are outside this phase.

## Rollback

Rollback is a normal revert of the repository documentation, evidence, tests,
and tooling commit. The added checker is read-only and has no host-side
rollback action. The manual proof-of-life workspace remains untouched.
