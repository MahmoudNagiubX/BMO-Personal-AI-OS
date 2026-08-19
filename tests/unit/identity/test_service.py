from __future__ import annotations

import json
from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from personal_ai_os.identity.contracts import EnrollmentGrant, HeartbeatRequest
from personal_ai_os.identity.errors import (
    AuthenticationError,
    CapabilityEscalationError,
    EnrollmentRejectedError,
    OwnerBootstrapError,
)
from personal_ai_os.identity.models import Device, DeviceCredential, Enrollment, Owner
from personal_ai_os.identity.security import generate_device_credential
from personal_ai_os.identity.service import IdentityService
from tests.unit.identity.conftest import ALL_SCOPES, NOW, provision_device


def test_owner_bootstrap_is_single_owner_and_not_hard_coded(session: Session) -> None:
    service = IdentityService(session, clock=lambda: NOW)

    owner = service.bootstrap_owner("Synthetic owner")

    assert owner.display_name == "Synthetic owner"
    with pytest.raises(OwnerBootstrapError, match="already complete"):
        service.bootstrap_owner("Second owner")
    assert len(session.scalars(select(Owner)).all()) == 1


def test_database_constraint_enforces_single_owner(session: Session) -> None:
    IdentityService(session, clock=lambda: NOW).bootstrap_owner("Synthetic owner")

    with pytest.raises(IntegrityError), session.begin():
        session.add(Owner(display_name="Concurrent owner", status="active"))


@pytest.mark.parametrize("scope", ["*", "admin", "device.*", "tool.execute"])
def test_enrollment_rejects_non_phase_six_scopes(session: Session, scope: str) -> None:
    owner = IdentityService(session, clock=lambda: NOW).bootstrap_owner("Synthetic owner")

    with pytest.raises(ValidationError, match="unsupported Phase 6 scope"):
        EnrollmentGrant(
            owner_id=owner.id,
            display_name="Synthetic client",
            device_kind="windows_client",
            platform="windows",
            scopes=[scope],
        )


def test_expired_and_replayed_enrollments_are_rejected(session: Session) -> None:
    current = [NOW]
    service = IdentityService(session, clock=lambda: current[0])
    owner = service.bootstrap_owner("Synthetic owner")
    grant = EnrollmentGrant(
        owner_id=owner.id,
        display_name="Synthetic client",
        device_kind="windows_client",
        platform="windows",
        scopes=["device.self.read"],
        ttl_minutes=1,
    )
    expired = service.create_enrollment(grant)
    current[0] = NOW + timedelta(minutes=2)
    with pytest.raises(EnrollmentRejectedError, match="invalid enrollment"):
        service.redeem_enrollment(expired.code)

    current[0] = NOW
    replayed = service.create_enrollment(grant)
    service.redeem_enrollment(replayed.code)
    with pytest.raises(EnrollmentRejectedError, match="invalid enrollment"):
        service.redeem_enrollment(replayed.code)


def test_plaintext_enrollment_and_credential_are_absent_at_rest(session: Session) -> None:
    _, issued, enrollment_code = provision_device(session)
    enrollment = session.scalar(select(Enrollment))
    credential = session.scalar(select(DeviceCredential))

    assert enrollment is not None
    assert credential is not None
    serialized = " ".join(
        str(value)
        for value in (
            enrollment.code_hash,
            credential.public_id,
            credential.secret_hash,
        )
    )
    assert enrollment_code not in serialized
    assert issued.raw not in serialized
    assert issued.raw.split(".", maxsplit=1)[1] not in serialized
    assert len(enrollment.code_hash) == 64
    assert len(credential.secret_hash) == 64


def test_sanitized_device_listing_contains_no_credential_material(session: Session) -> None:
    service, issued, _ = provision_device(session)

    listing = json.dumps(
        [device.model_dump(mode="json") for device in service.list_devices()],
        sort_keys=True,
    )

    assert issued.raw not in listing
    assert issued.raw.split(".", maxsplit=1)[1] not in listing
    assert "secret_hash" not in listing
    assert "public_id" not in listing


def test_authentication_negative_matrix_fails_closed(session: Session) -> None:
    service, issued, _ = provision_device(session)
    public_id, _ = issued.raw.split(".", maxsplit=1)
    wrong_secret = f"{public_id}.{'x' * 43}"

    for raw in ("malformed", f"{'u' * 16}.{'s' * 43}", wrong_secret):
        with pytest.raises(AuthenticationError, match="invalid device credential"):
            service.authenticate(raw)

    principal = service.authenticate(issued.raw)
    assert principal.device_id == issued.device_id

    with session.begin():
        credential = session.get(DeviceCredential, issued.credential_id)
        assert credential is not None
        credential.revoked_at = NOW
    with pytest.raises(AuthenticationError):
        service.authenticate(issued.raw)


def test_revoked_device_and_disabled_owner_fail_authentication(session: Session) -> None:
    service, issued, _ = provision_device(session)
    with session.begin():
        device = session.get(Device, issued.device_id)
        assert device is not None
        device.status = "revoked"
    with pytest.raises(AuthenticationError):
        service.authenticate(issued.raw)

    with session.begin():
        device.status = "active"
        owner = session.get(Owner, device.owner_id)
        assert owner is not None
        owner.status = "disabled"
    with pytest.raises(AuthenticationError):
        service.authenticate(issued.raw)


def test_heartbeat_updates_current_subset_and_rejects_escalation(session: Session) -> None:
    service, issued, _ = provision_device(session)
    principal = service.authenticate(issued.raw)

    updated = service.heartbeat(
        principal,
        HeartbeatRequest(
            software_version="1.2.3",
            reported_capabilities=["system.health"],
        ),
    )

    assert updated.software_version == "1.2.3"
    assert updated.reported_capabilities == ["system.health"]
    with pytest.raises(CapabilityEscalationError):
        service.heartbeat(
            principal,
            HeartbeatRequest(reported_capabilities=["shell.unrestricted"]),
        )
    assert service.device_self(principal).reported_capabilities == ["system.health"]


def test_rotation_invalidates_only_used_credential(session: Session) -> None:
    service, issued, _ = provision_device(session)
    other = generate_device_credential()
    with session.begin():
        other_row = DeviceCredential(
            device_id=issued.device_id,
            public_id=other.public_id,
            secret_hash=other.secret_hash,
        )
        session.add(other_row)
    principal = service.authenticate(issued.raw)

    replacement = service.rotate_credential(principal)

    with pytest.raises(AuthenticationError):
        service.authenticate(issued.raw)
    assert service.authenticate(replacement.raw).device_id == issued.device_id
    assert service.authenticate(other.raw).device_id == issued.device_id


def test_revoking_one_device_does_not_affect_another(session: Session) -> None:
    service, first, _ = provision_device(session)
    owner_id = service.authenticate(first.raw).owner_id
    second_enrollment = service.create_enrollment(
        EnrollmentGrant(
            owner_id=owner_id,
            display_name="Second synthetic client",
            device_kind="android_client",
            platform="android",
            scopes=ALL_SCOPES,
        )
    )
    second = service.redeem_enrollment(second_enrollment.code)

    service.revoke_device(first.device_id)

    with pytest.raises(AuthenticationError):
        service.authenticate(first.raw)
    assert service.authenticate(second.raw).device_id == second.device_id
