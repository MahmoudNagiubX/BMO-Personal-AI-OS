"""Redeem one owner-created enrollment without exposing its code or credential."""

from __future__ import annotations

import getpass
import json
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from personal_ai_os.identity.contracts import EnrollmentRedeemResponse
from personal_ai_os.satellites.windows.config import WindowsSatelliteSettings
from personal_ai_os.satellites.windows.credentials import WindowsCredentialStore


def _http_url(endpoint: str, path: str) -> str:
    parsed = urlsplit(endpoint)
    scheme = "https" if parsed.scheme == "wss" else "http"
    return urlunsplit((scheme, parsed.netloc, path, "", ""))


def main() -> None:
    settings = WindowsSatelliteSettings()  # type: ignore[call-arg]
    code = getpass.getpass("One-time Phase 9 enrollment code: ")
    payload = json.dumps({"code": code}, separators=(",", ":")).encode("utf-8")
    code = ""
    request = Request(
        _http_url(settings.endpoint, "/api/v1/enrollment/redeem"),
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        issued = EnrollmentRedeemResponse.model_validate_json(response.read())
    WindowsCredentialStore().write(issued.credential)
    print("PHASE_09_ENROLLMENT_STORED_IN_WINDOWS_CREDENTIAL_MANAGER")


if __name__ == "__main__":
    main()
