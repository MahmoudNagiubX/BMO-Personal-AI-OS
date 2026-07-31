# Security Policy

Personal AI OS will eventually handle private personal data and control approved devices. Security failures must be treated as product failures, not optional hardening work.

## Reporting

Do not publish suspected vulnerabilities, secrets, personal data, device identifiers, network details, or exploit steps in a public issue. Report them privately to the repository owner.

## Never commit

- `.env` files or credentials.
- API, Home Assistant, MQTT, GitHub, email, calendar, or device tokens.
- SSH keys, certificates, cookies, browser profiles, or password stores.
- Database dumps, backups, raw recordings, screenshots, private documents, or production logs.
- Real personal data in fixtures.

## Required design properties

- Least privilege and per-device scopes.
- Explicit approvals for consequential actions.
- Typed and allowlisted device tools.
- Fail-closed authorization.
- Audit records for actions and approvals.
- Sandboxed browser and untrusted-content processing.
- Local-first defaults and external analytics disabled.
- Clear retention and deletion behavior.

## Supported versions

Until the first tagged release, only the latest commit on `main` is supported. Security fixes receive priority over features.

## Incident response

1. Disconnect the affected device or service.
2. Revoke exposed credentials and device tokens.
3. Preserve sanitized logs and correlation IDs.
4. Determine affected data and actions.
5. Patch and add a regression test.
6. Restore from a verified backup when necessary.
7. Record the incident and recovery without storing sensitive evidence in Git.
