"""List sanitized device registry metadata through a local operation."""

from __future__ import annotations

import json

from personal_ai_os.identity.service import IdentityService
from scripts.phase_06._common import identity_session


def main() -> None:
    with identity_session() as session:
        devices = IdentityService(session).list_devices()
    payload = [device.model_dump(mode="json") for device in devices]
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
