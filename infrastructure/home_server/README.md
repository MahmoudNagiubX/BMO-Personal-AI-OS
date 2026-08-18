# VENOM Lenovo control-plane foundation

This directory is the repository-side foundation for the verified physical
VENOM host. It does not deploy software, open ports, or replace the canonical
backend under `src/personal_ai_os/`.

## Runtime identity and topology

- Runtime name: `VENOM`
- Hostname: `venom-server`
- Linux user: `venom`
- Host: Lenovo G450, Ubuntu Server 24.04.4 LTS AMD64, headless
- ASUS TUF: Ollama, Qwen3.5 4B generation/vision, and BGE-M3 embeddings
- Repository source of truth: ASUS TUF -> GitHub -> reviewed commit -> Lenovo SSH deployment

The manual `~/venom/core/brain` FastAPI proof-of-life workspace remains
historical bootstrap evidence. It is not production code and must not receive
a second backend implementation. Future deployment comes from an exact,
reviewed repository commit.

## Evidence

`evidence/venom_foundation_handoff.json` is a sanitized owner-provided handoff
record. Validate it with:

```bash
uv run python scripts/phase_01/validate_foundation_evidence.py \
  --input infrastructure/home_server/evidence/venom_foundation_handoff.json
```

The handoff records the completed installation, identity, SMART, and proof of
life facts. It intentionally keeps the physical safety gate `incomplete`.
The read-only local preflight is available at
`scripts/phase_01/check_foundation_prerequisites.sh`; it must be run by a
human on VENOM when physical access is authorized.

## Runbooks

- `runbooks/01-foundation-inventory.md` — network, memory, storage, thermal,
  and system evidence.
- `runbooks/02-ssh-firewall.md` — key-auth proof and private-LAN UFW scope.
- `runbooks/03-logs-backup-restore.md` — bounded logs and real restore proof.
- `runbooks/04-reboot-and-stability.md` — restart recovery and 24-hour/7-day gates.

All privileged, physical, destructive, or long-running actions remain manual
owner operations. No runbook authorizes public exposure, blind LVM changes,
uncontrolled stress, final swap sizing, production Docker admission, or Phase
5B deployment.
