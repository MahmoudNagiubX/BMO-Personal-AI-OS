# Runbook 02 — SSH and private-LAN firewall

This runbook is a manual hardening plan. It is not an authorization for Codex
to connect to VENOM or change its configuration.

1. Keep password login until key authentication is proven. Create or select a
   dedicated key on the ASUS TUF, copy only its public key to `venom`, then open
   a second session and verify key login and the recovery path.
2. Only after that proof, validate the SSH configuration and remove root SSH.
   Password disablement is optional until a tested recovery path exists; never
   risk locking the owner out.
3. Identify the trusted private LAN subnet from the router and host evidence.
   Keep UFW default inbound deny and scope SSH to that subnet when practical.
   No public port forwarding is allowed.
4. Do not expose PostgreSQL, Ollama, MQTT, Home Assistant, or internal APIs.
   Do not open port 8000 for the disposable FastAPI proof service.
5. Verify after any change with a second SSH session, `ufw status verbose`, and
   a local service-listening check. Record only pass/fail and the scoped subnet
   in sanitized evidence.

The later deployment path remains ASUS TUF -> GitHub review -> exact commit ->
manual SSH deployment to VENOM. Do not hand-edit production source on the host.
