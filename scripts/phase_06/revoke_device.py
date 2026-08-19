"""Soft-revoke one explicitly identified device through a local operation."""

from __future__ import annotations

import argparse
from uuid import UUID

from personal_ai_os.identity.errors import DeviceNotFoundError
from personal_ai_os.identity.service import IdentityService
from scripts.phase_06._common import identity_session


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Revoke one Phase 6 device")
    result.add_argument("--device-id", type=UUID, required=True)
    return result


def main() -> None:
    args = parser().parse_args()
    try:
        with identity_session() as session:
            IdentityService(session).revoke_device(args.device_id)
    except DeviceNotFoundError as error:
        raise SystemExit("DEVICE_REVOCATION_REFUSED: device does not exist") from error
    print(f"DEVICE_REVOCATION_PASS device_id={args.device_id}")


if __name__ == "__main__":
    main()
