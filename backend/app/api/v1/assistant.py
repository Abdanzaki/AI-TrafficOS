"""AI Assistant REST API router (Phase 9 Stage 4).

Provides authenticated chat interaction with grounded traffic engineering tools,
deterministic Natural Language Understanding (NLU), and immutable audit trails.
"""

import logging
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.api.v1.auth import get_client_ip
from app.assistant.providers import get_llm_provider
from app.core.audit import log_audit
from app.core.database import get_db
from app.models.auth import User

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/assistant",
    tags=["assistant"],
)


class ChatHistoryItem(BaseModel):
    """Historical chat turn in the active conversation."""

    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=4000)


class AssistantChatRequest(BaseModel):
    """Request payload for assistant chat turn."""

    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="User query in natural language",
    )
    conversation_history: Optional[list[ChatHistoryItem]] = Field(
        default=None,
        max_length=20,
        description="Prior conversation turns for context carryover (max 20)",
    )
    junction_id: Optional[int] = Field(
        default=None,
        description="Optional explicitly targeted physical junction ID",
    )


class ToolCallRecord(BaseModel):
    """Record of domain tool executed during assistant answering."""

    tool: str
    args: dict[str, Any]
    provenance: str


class ProvenanceSummary(BaseModel):
    """Counts of distinct data items returned across provenance classifications."""

    observed: int = 0
    predicted: int = 0
    recommended: int = 0


class AssistantChatResponse(BaseModel):
    """Structured assistant response with grounded citations and provenance breakdown."""

    answer: str
    tool_calls: list[ToolCallRecord]
    provenance_summary: ProvenanceSummary
    confidence: Literal["high", "medium", "low"]
    model: str


@router.post(
    "/chat",
    response_model=AssistantChatResponse,
    status_code=status.HTTP_200_OK,
    summary="Engage with AI TrafficOS assistant",
)
async def chat(
    payload: AssistantChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> AssistantChatResponse:
    """Process user message against grounded tools with role-based access control.

    GUARANTEES:
    - Accessible to all authenticated roles ('admin', 'traffic_officer', 'analyst').
    - Tools enforce per-domain RBAC (e.g. simulation and routing reserved for operators).
    - Every chat query is audit-logged to `audit_logs` without storing unbounded dialogue history.
    - Zero data fabrication: empty database queries result in explicit 'no data' markers.
    """
    caller_role = current_user.role.name if current_user.role else "analyst"
    provider = get_llm_provider()

    history_dicts = (
        [item.model_dump() for item in payload.conversation_history]
        if payload.conversation_history
        else None
    )

    context = {
        "db": db,
        "caller_role": caller_role,
        "conversation_history": history_dicts,
        "junction_id": payload.junction_id,
    }

    nlu_result = await provider.process_query(
        prompt=payload.message,
        context=context,
    )

    # Immutable audit logging (logs current message metadata, NEVER full dialogue history)
    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="assistant.chat",
        actor_user_id=current_user.id,
        entity_type="assistant",
        entity_id=None,
        details={
            "message": payload.message,
            "junction_id": payload.junction_id,
            "intent": nlu_result.intent,
            "caller_role": caller_role,
            "model": provider.name,
            "confidence": nlu_result.confidence,
            "tools_called": [tc["tool"] for tc in nlu_result.tool_calls],
        },
        ip_address=client_ip,
    )
    await db.commit()

    tool_call_records = [
        ToolCallRecord(
            tool=tc["tool"],
            args=tc.get("args", {}),
            provenance=tc.get("provenance", "observed"),
        )
        for tc in nlu_result.tool_calls
    ]

    conf_str: Literal["high", "medium", "low"] = (
        nlu_result.confidence
        if nlu_result.confidence in ("high", "medium", "low")
        else "high"
    )

    return AssistantChatResponse(
        answer=nlu_result.answer,
        tool_calls=tool_call_records,
        provenance_summary=ProvenanceSummary(
            observed=nlu_result.provenance_summary.get("observed", 0),
            predicted=nlu_result.provenance_summary.get("predicted", 0),
            recommended=nlu_result.provenance_summary.get("recommended", 0),
        ),
        confidence=conf_str,
        model=provider.name,
    )
