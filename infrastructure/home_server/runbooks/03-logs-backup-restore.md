# Runbook 03 — bounded logs and backup/restore

Run this only after the resource baseline has been reviewed. It must not start
the full product stack.

1. Set a reviewed journald retention/size bound and application log rotation.
   Preserve enough logs for failure diagnosis and monitor root free space.
2. Define the backup scope for configuration, deployment manifests, sanitized
   evidence, and later service data. Never commit secrets or database dumps.
3. Keep at least one encrypted copy off VENOM. A second copy on the Lenovo is
   not an off-device backup.
4. Restore a small synthetic fixture to a separate temporary location and
   verify its checksum and readability. Record the result without storing
   personal data or credentials.
5. Do not admit Docker, PostgreSQL, Home Assistant, or MQTT until memory, swap,
   storage, thermal, and backup evidence has been reviewed.

Rollback is to the last reviewed host configuration and the verified backup.
Any service or log-policy change must have a tested recovery path before the
next stability gate.
