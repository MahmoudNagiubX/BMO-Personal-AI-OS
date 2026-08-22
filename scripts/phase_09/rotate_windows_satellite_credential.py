"""Rotate the current device credential and atomically replace its secure-store value."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from personal_ai_os.identity.contracts import CredentialRotationResponse
from personal_ai_os.satellites.windows.config import WindowsSatelliteSettings
from personal_ai_os.satellites.windows.credentials import WindowsCredentialStore


def main() -> None:
    settings = WindowsSatelliteSettings()  # type: ignore[call-arg]
    store = WindowsCredentialStore()
    current = store.read()
    if current is None:
        raise SystemExit("Phase 9 satellite credential is not enrolled")
    parsed = urlsplit(settings.endpoint)
    scheme = "https" if parsed.scheme == "wss" else "http"
    url = urlunsplit((scheme, parsed.netloc, "/api/v1/devices/me/credentials/rotate", "", ""))
    request = Request(
        url,
        data=b"{}",
        headers={"Authorization": f"Bearer {current}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        issued = CredentialRotationResponse.model_validate_json(response.read())
    store.write(issued.credential)
    print("PHASE_09_CREDENTIAL_ROTATION_PASS")


if __name__ == "__main__":
    main()
