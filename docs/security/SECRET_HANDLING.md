# Secret Handling

## Storage

- Development secrets live in an ignored local `.env` only during early phases.
- Production secrets must move to an OS-level or dedicated secret store before deployment.
- Device credentials are unique and revocable.
- Never reuse development credentials in production.

## Logging

- Never log authorization headers, cookies, tokens, passwords, private keys, database URLs with passwords, or raw personal payloads.
- Sanitize exception context and tool traces.

## Rotation

Document creation date, owner, scope, storage, and rotation procedure for each secret. Revoke a device token immediately when a device is lost or reinstalled.

## Repository checks

`scripts/verify_governance.py` is an early guard, not a complete secret-management solution. Later phases must add stronger scanning and CI controls.
