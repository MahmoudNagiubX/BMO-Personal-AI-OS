"""Bounded adapter from model proposals to the Phase 8 authority."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from personal_ai_os.identity.contracts import DevicePrincipal
from personal_ai_os.model_gateway.contracts import ToolProposal
from personal_ai_os.tools.contracts import ToolCallRequest, ToolCallResponse
from personal_ai_os.tools.service import ToolPlatformService


@dataclass(frozen=True, slots=True)
class AgentToolLoopResult:
    """Data-only proposal handling result; approval pauses execution."""

    proposals_seen: int
    requests: tuple[ToolCallResponse, ...]
    paused_for_approval: bool


class BoundedAgentToolRuntime:
    """Turn at most three model proposals into durable requests, never direct calls."""

    MAX_TOOL_PROPOSALS = 3

    def __init__(self, service: ToolPlatformService) -> None:
        self.service = service

    def submit_proposals(
        self,
        principal: DevicePrincipal,
        proposals: tuple[ToolProposal, ...],
        *,
        idempotency_prefix: str,
        conversation_id: UUID | None = None,
        run_id: UUID | None = None,
    ) -> AgentToolLoopResult:
        if len(proposals) > self.MAX_TOOL_PROPOSALS:
            proposals = proposals[: self.MAX_TOOL_PROPOSALS]
        responses: list[ToolCallResponse] = []
        for index, proposal in enumerate(proposals):
            # ModelGateway proposals have no risk, policy, executor, or approval fields.
            response = self.service.request_tool(
                principal,
                ToolCallRequest(
                    name=proposal.name,
                    version=1,
                    arguments=dict(proposal.arguments),
                    idempotency_key=f"{idempotency_prefix}-{index:02d}",
                    conversation_id=conversation_id,
                    run_id=run_id,
                ),
            )
            responses.append(response)
        return AgentToolLoopResult(
            proposals_seen=len(proposals),
            requests=tuple(responses),
            paused_for_approval=any(
                response.status.value == "awaiting_approval" for response in responses
            ),
        )


__all__ = ["AgentToolLoopResult", "BoundedAgentToolRuntime"]
