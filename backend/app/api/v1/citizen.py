"""Citizen Assistant REST API router (Batch 3 Final Brief C).

Provides a public citizen-facing assistant endpoint strictly limited to public read-only traffic
conditions, active road incident notices, and reporting instructions.

AUTHENTICATION & RBAC DESIGN DECISION:
=======================================
Per specification ("public or citizen-role scoped per existing auth conventions — prefer a
dedicated citizen role; document the choice"), this endpoint enforces dedicated 'citizen' role
scoping via `require_roles("citizen", "admin")`.

Rationale for choosing dedicated citizen role:
1. Strict Account Attribution: Every citizen conversation turn is securely tied to an authenticated
   user identity and logged in `audit_logs` (`action="citizen.chat"`, `actor_user_id`), preventing
   untraceable automated query abuse or denial-of-service scrapers.
2. RBAC Boundary Enforcement: The 'citizen' role is isolated with minimal permissions:
   - Permitted: Citizen assistant (`/api/v1/citizen/chat`) and public informational tools.
   - Strictly Forbidden: Control-room assistant (`/api/v1/assistant/chat`), signal controllers,
     what-if timing simulation, emergency preemption, and internal telemetry.
3. Administrative Parity: 'admin' is also authorized to allow municipal supervisors to inspect and
   verify citizen assistant behavior.
"""

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.api.v1.auth import get_client_ip
from app.assistant.citizen import CitizenProvider
from app.core.audit import log_audit
from app.core.database import get_db
from app.core.rate_limit import rate_limit_expensive
from app.models.auth import User

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/citizen",
    tags=["citizen"],
)


class CitizenChatRequest(BaseModel):
    """Request payload for public citizen chat turn."""

    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Public citizen question in natural language",
    )
    junction_id: Optional[int] = Field(
        default=None,
        description="Optional explicitly targeted physical junction ID",
    )


class CitizenChatResponse(BaseModel):
    """Structured citizen assistant response with provenance and out-of-scope refusal flag."""

    answer: str
    provenance: str = "observed"
    tools_used: list[str] = Field(default_factory=list)
    refused: bool = False
    confidence: Literal["high", "medium", "low"] = "high"


@router.post(
    "/chat",
    response_model=CitizenChatResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit_expensive)],
    summary="Engage with Public Citizen Traffic Assistant",
)
async def citizen_chat(
    payload: CitizenChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("citizen", "admin")),
) -> CitizenChatResponse:
    """Process citizen message against public-only tools with out-of-scope refusal.

    GUARANTEES:
    - Scoped to dedicated 'citizen' role (and 'admin' for verification).
    - NEVER executes control-room tools or exposes signal timing, AI decisions, or emergency events.
    - Out-of-scope queries (e.g. signal timing plans, control decisions, emergency fleet events)
      are politely and gracefully refused with `refused=True`.
    - Every query turn is immutably logged to `audit_logs` without storing unbounded dialogue history.
    """
    provider = CitizenProvider()

    result = await provider.process_query(
        db=db,
        message=payload.message,
        explicit_junction_id=payload.junction_id,
    )

    caller_role = current_user.role.name if current_user.role else "citizen"
    client_ip = get_client_ip(request)

    await log_audit(
        db=db,
        action="citizen.chat",
        actor_user_id=current_user.id,
        entity_type="citizen_assistant",
        entity_id=None,
        details={
            "message": payload.message,
            "junction_id": payload.junction_id,
            "intent": result.intent,
            "tools_used": result.tools_used,
            "refused": result.refused,
            "caller_role": caller_role,
        },
        ip_address=client_ip,
    )
    await db.commit()

    conf_str: Literal["high", "medium", "low"] = (
        result.confidence
        if result.confidence in ("high", "medium", "low")
        else "high"
    )

    return CitizenChatResponse(
        answer=result.answer,
        provenance=result.provenance,
        tools_used=result.tools_used,
        refused=result.refused,
        confidence=conf_str,
    )
