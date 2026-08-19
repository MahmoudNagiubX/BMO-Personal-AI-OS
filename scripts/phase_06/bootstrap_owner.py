"""Bootstrap the one Phase 6 owner through a local database operation."""

from __future__ import annotations

import argparse

from personal_ai_os.identity.errors import OwnerBootstrapError
from personal_ai_os.identity.service import IdentityService
from scripts.phase_06._common import identity_session


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Bootstrap the first local BMO owner")
    result.add_argument("--display-name", required=True, help="Bounded owner display label")
    return result


def main() -> None:
    args = parser().parse_args()
    try:
        with identity_session() as session:
            owner = IdentityService(session).bootstrap_owner(args.display_name)
    except OwnerBootstrapError as error:
        raise SystemExit(f"OWNER_BOOTSTRAP_REFUSED: {error}") from error
    print(f"OWNER_BOOTSTRAP_PASS owner_id={owner.id} status={owner.status}")


if __name__ == "__main__":
    main()
