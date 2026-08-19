from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from personal_ai_os.db.base import Base
from personal_ai_os.identity.contracts import PHASE_8_SCOPES, EnrollmentGrant
from personal_ai_os.identity.service import IdentityService
from personal_ai_os.model_gateway.contracts import ToolProposal
from personal_ai_os.tools.agent_runtime import BoundedAgentToolRuntime
from personal_ai_os.tools.contracts import (
    ApprovalStatus,
    ToolCallRequest,
    ToolCallStatus,
    ToolObservationStatus,
)
from personal_ai_os.tools.errors import (
    ApprovalError,
    ToolBudgetError,
    ToolConflictError,
    ToolPlatformError,
    ToolSchemaError,
)
from personal_ai_os.tools.registry import argument_digest, default_registry, deterministic_preview
from personal_ai_os.tools.service import ToolPlatformService


@pytest.fixture
def sqlite_session() -> Generator[Session, None, None]:
    engine: Engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def identity(sqlite_session: Session) -> tuple[Session, Any]:
    service = IdentityService(sqlite_session)
    owner = service.bootstrap_owner("Synthetic Phase 8 owner")
    enrollment = service.create_enrollment(
        EnrollmentGrant(
            owner_id=owner.id,
            display_name="Synthetic Phase 8 device",
            device_kind="windows_client",
            platform="windows",
            scopes=sorted(PHASE_8_SCOPES),
        )
    )
    issued = service.redeem_enrollment(enrollment.code)
    return sqlite_session, service.authenticate(issued.raw)


def test_registry_is_static_strict_and_preview_is_deterministic() -> None:
    registry = default_registry()
    descriptor = registry.resolve("phase8.status.read", 1)
    assert descriptor.risk_level.value == "read"
    assert registry.validate_arguments(descriptor, {"resource": "platform"}) == {
        "resource": "platform"
    }
    with pytest.raises(ToolSchemaError):
        registry.validate_arguments(descriptor, {"resource": "platform", "extra": True})
    with pytest.raises(ToolSchemaError):
        registry.validate_arguments(descriptor, {"resource": 1})
    assert argument_digest({"b": 2, "a": 1}) == argument_digest({"a": 1, "b": 2})
    preview = deterministic_preview(descriptor, {"resource": "platform", "api_token": "secret"})
    assert preview["arguments"]["api_token"] == "[REDACTED]"
    with pytest.raises(ToolPlatformError):
        registry.resolve("phase8.status.read", 2)


def test_allow_replay_and_typed_success(
    sqlite_session: Session, identity: tuple[Session, Any]
) -> None:
    _, principal = identity
    service = ToolPlatformService(sqlite_session)
    request = ToolCallRequest(
        name="phase8.status.read",
        version=1,
        arguments={"resource": "platform"},
        idempotency_key="phase8-status-000001",
    )
    first = service.request_tool(principal, request)
    replay = service.request_tool(principal, request)
    assert first.status is ToolCallStatus.APPROVED
    assert replay.replayed is True
    observation = service.execute_tool_call(principal, first.id)
    assert observation.status is ToolObservationStatus.SUCCEEDED
    assert service.execute_tool_call(principal, first.id).status is ToolObservationStatus.SUCCEEDED


def test_approval_is_exactly_bound_and_consumed(
    sqlite_session: Session, identity: tuple[Session, Any]
) -> None:
    _, principal = identity
    service = ToolPlatformService(sqlite_session)
    response = service.request_tool(
        principal,
        ToolCallRequest(
            name="phase8.consequential.echo",
            version=1,
            arguments={"message": "synthetic"},
            idempotency_key="phase8-approval-0001",
        ),
    )
    assert response.status is ToolCallStatus.AWAITING_APPROVAL
    assert response.approval_id is not None
    with pytest.raises(ToolConflictError):
        service.execute_tool_call(principal, response.id, arguments={"message": "changed"})
    decision = service.decide_approval(principal, response.approval_id, approve=True)
    assert decision.status is ApprovalStatus.APPROVED
    assert (
        service.execute_tool_call(principal, response.id).status is ToolObservationStatus.SUCCEEDED
    )
    with pytest.raises(ApprovalError):
        service.decide_approval(principal, response.approval_id, approve=False)


@pytest.mark.parametrize("name", ["phase8.forbidden.shell", "phase8.offline.read"])
def test_forbidden_and_unavailable_never_execute(
    sqlite_session: Session, identity: tuple[Session, Any], name: str
) -> None:
    _, principal = identity
    service = ToolPlatformService(sqlite_session)
    response = service.request_tool(
        principal,
        ToolCallRequest(name=name, version=1, arguments={}, idempotency_key=f"deny-{name}"),
    )
    assert response.status is ToolCallStatus.DENIED


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("phase8.invalid.output", "output_schema_invalid"),
        ("phase8.verification.fail", "verification_failed"),
    ],
)
def test_output_and_verification_failures_are_not_success(
    sqlite_session: Session, identity: tuple[Session, Any], name: str, expected: str
) -> None:
    _, principal = identity
    service = ToolPlatformService(sqlite_session)
    response = service.request_tool(
        principal,
        ToolCallRequest(name=name, version=1, arguments={}, idempotency_key=f"fail-{name}"),
    )
    observation = service.execute_tool_call(principal, response.id)
    assert observation.status is ToolObservationStatus.FAILED
    assert observation.failure_code == expected


def test_cancel_and_budget_are_fail_closed(
    sqlite_session: Session, identity: tuple[Session, Any]
) -> None:
    _, principal = identity
    service = ToolPlatformService(sqlite_session)
    requests = [
        service.request_tool(
            principal,
            ToolCallRequest(
                name="phase8.status.read",
                version=1,
                arguments={"resource": "platform"},
                idempotency_key=f"phase8-budget-{index:02d}",
            ),
        )
        for index in range(4)
    ]
    for request in requests[:3]:
        assert (
            service.execute_tool_call(principal, request.id).status
            is ToolObservationStatus.SUCCEEDED
        )
    with pytest.raises(ToolBudgetError):
        service.execute_tool_call(principal, requests[3].id)
    cancelled = service.cancel_tool_call(principal, requests[3].id)
    assert cancelled.status is ToolCallStatus.CANCELLED


def test_bounded_agent_runtime_keeps_model_proposals_as_data(
    sqlite_session: Session, identity: tuple[Session, Any]
) -> None:
    _, principal = identity
    service = ToolPlatformService(sqlite_session)
    result = BoundedAgentToolRuntime(service).submit_proposals(
        principal,
        (ToolProposal(name="phase8.status.read", arguments={"resource": "platform"}),),
        idempotency_prefix="agent-loop-0001",
    )
    assert result.proposals_seen == 1
    assert result.requests[0].status is ToolCallStatus.APPROVED
    assert result.paused_for_approval is False
