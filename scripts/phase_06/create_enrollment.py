"""Create one short-lived owner-approved device enrollment locally."""

from __future__ import annotations

import argparse
from uuid import UUID

from pydantic import ValidationError

from personal_ai_os.identity.contracts import PHASE_6_SCOPES, EnrollmentGrant
from personal_ai_os.identity.errors import EnrollmentRejectedError
from personal_ai_os.identity.service import IdentityService
from scripts.phase_06._common import identity_session


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Create a one-time Phase 6 enrollment")
    result.add_argument("--owner-id", type=UUID, required=True)
    result.add_argument("--display-name", required=True)
    result.add_argument(
        "--device-kind",
        required=True,
        choices=(
            "windows_client",
            "android_client",
            "room_node",
            "windows_satellite",
            "browser_worker",
            "internal_service",
            "bridge",
        ),
    )
    result.add_argument(
        "--platform", required=True, choices=("windows", "android", "linux", "embedded", "service")
    )
    result.add_argument("--software-version")
    result.add_argument("--scope", action="append", required=True, choices=sorted(PHASE_6_SCOPES))
    result.add_argument("--capability", action="append", default=[])
    result.add_argument("--ttl-minutes", type=int, default=10)
    return result


def main() -> None:
    args = parser().parse_args()
    try:
        grant = EnrollmentGrant(
            owner_id=args.owner_id,
            display_name=args.display_name,
            device_kind=args.device_kind,
            platform=args.platform,
            software_version=args.software_version,
            scopes=args.scope,
            capabilities=args.capability,
            ttl_minutes=args.ttl_minutes,
        )
        with identity_session() as session:
            issued = IdentityService(session).create_enrollment(grant)
    except (ValidationError, EnrollmentRejectedError) as error:
        raise SystemExit("ENROLLMENT_CREATE_REFUSED") from error
    print(f"ENROLLMENT_ID={issued.enrollment_id}")
    print(f"EXPIRES_AT={issued.expires_at.isoformat()}")
    print(f"ENROLLMENT_CODE={issued.code}")
    print("Store this one-time code securely; it is not retained in plaintext.")


if __name__ == "__main__":
    main()
