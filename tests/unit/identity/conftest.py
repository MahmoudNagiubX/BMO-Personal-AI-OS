from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from personal_ai_os.db.base import Base
from personal_ai_os.identity.contracts import EnrollmentGrant
from personal_ai_os.identity.service import IdentityService, IssuedCredential

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
ALL_SCOPES = [
    "device.self.read",
    "device.heartbeat.write",
    "device.capabilities.report",
    "device.credential.rotate",
]


@pytest.fixture
def sqlite_engine() -> Generator[Engine, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def session(sqlite_engine: Engine) -> Generator[Session, None, None]:
    factory = sessionmaker(bind=sqlite_engine, expire_on_commit=False)
    with factory() as value:
        yield value


def provision_device(
    session: Session,
    *,
    scopes: list[str] | None = None,
    capabilities: list[str] | None = None,
    display_name: str = "Synthetic client",
) -> tuple[IdentityService, IssuedCredential, str]:
    service = IdentityService(session, clock=lambda: NOW)
    owner = service.bootstrap_owner("Synthetic owner")
    issued_enrollment = service.create_enrollment(
        EnrollmentGrant(
            owner_id=owner.id,
            display_name=display_name,
            device_kind="windows_client",
            platform="windows",
            scopes=ALL_SCOPES if scopes is None else scopes,
            capabilities=["screen.observe", "system.health"]
            if capabilities is None
            else capabilities,
            ttl_minutes=10,
        )
    )
    issued_credential = service.redeem_enrollment(issued_enrollment.code)
    return service, issued_credential, issued_enrollment.code
