from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from personal_ai_os.app import create_app
from personal_ai_os.core.config import get_settings
from personal_ai_os.identity.contracts import EnrollmentGrant
from personal_ai_os.identity.errors import EnrollmentRejectedError
from personal_ai_os.identity.models import Device, DeviceCredential
from personal_ai_os.identity.service import IdentityService

pytestmark = pytest.mark.integration
EXPECTED_REVISION = "20260819_0002"


@pytest.fixture
def test_database_url() -> str:
    value = os.environ.get("BMO_TEST_DATABASE_URL")
    if not value:
        pytest.skip("BMO_TEST_DATABASE_URL is not set")
    parsed = urlsplit(value)
    if parsed.scheme != "postgresql+psycopg":
        pytest.fail("BMO_TEST_DATABASE_URL must use postgresql+psycopg")
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        pytest.fail("integration tests only accept a localhost PostgreSQL URL")
    if not parsed.path or parsed.path == "/":
        pytest.fail("BMO_TEST_DATABASE_URL must include a database name")
    return value


def test_postgresql_connection_and_vector_extension(test_database_url: str) -> None:
    engine = create_engine(test_database_url, pool_pre_ping=True, echo=False)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar_one() == 1
            extension = connection.execute(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            ).scalar_one_or_none()
            assert extension == "vector"
    finally:
        engine.dispose()


def test_alembic_head_is_applied(test_database_url: str) -> None:
    engine = create_engine(test_database_url, pool_pre_ping=True, echo=False)
    try:
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert revision == EXPECTED_REVISION
    finally:
        engine.dispose()


def test_readiness_uses_real_database(
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BMO_ENVIRONMENT", "test")
    monkeypatch.setenv("BMO_DATABASE_URL", test_database_url)
    get_settings.cache_clear()
    app = create_app()
    try:
        with TestClient(app) as client:
            response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ready"}
    finally:
        get_settings.cache_clear()


def test_concurrent_enrollment_redemption_has_exactly_one_success(
    test_database_url: str,
) -> None:
    engine = create_engine(test_database_url, pool_pre_ping=True, echo=False)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE owners CASCADE"))
        with factory() as session:
            service = IdentityService(session)
            owner = service.bootstrap_owner("Synthetic concurrent owner")
            enrollment = service.create_enrollment(
                EnrollmentGrant(
                    owner_id=owner.id,
                    display_name="Synthetic concurrent client",
                    device_kind="windows_client",
                    platform="windows",
                    scopes=["device.self.read"],
                    capabilities=["system.health"],
                )
            )

        barrier = Barrier(2)

        def redeem_once() -> bool:
            with factory() as session:
                barrier.wait(timeout=5)
                try:
                    IdentityService(session).redeem_enrollment(enrollment.code)
                except EnrollmentRejectedError:
                    return False
                return True

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: redeem_once(), range(2)))

        with factory() as session:
            device_count = session.scalar(
                select(func.count()).select_from(Device).where(Device.owner_id == owner.id)
            )
            credential_count = session.scalar(
                select(func.count())
                .select_from(DeviceCredential)
                .join(Device, Device.id == DeviceCredential.device_id)
                .where(Device.owner_id == owner.id, DeviceCredential.revoked_at.is_(None))
            )
        assert sorted(results) == [False, True]
        assert device_count == 1
        assert credential_count == 1
    finally:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE owners CASCADE"))
        engine.dispose()
