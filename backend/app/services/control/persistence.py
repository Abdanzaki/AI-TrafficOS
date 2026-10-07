"""Persistence store and lifecycle management for AI control decisions.

CRITICAL ARCHITECTURAL SAFETY INVARIANT:
----------------------------------------
This module handles persistence and lifecycle tracking for advisory control decisions
stored in `ai_decisions`. It enforces strict human-in-the-loop lifecycle transitions:
recommendations start in 'proposed' state and can only transition to 'applied' or 'reverted'.
"""

from datetime import datetime, timezone
import logging
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.ai import AIDecision
from app.services.control.schemas import Decision

logger = logging.getLogger(__name__)

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"applied", "reverted"},
    "applied": {"reverted"},
    "reverted": set(),
}


class DecisionStore:
    """Persistence manager for AIDecision ORM rows."""

    @classmethod
    async def save(
        cls,
        session: AsyncSession,
        decision: Decision,
        decided_by_user_id: Optional[int] = None,
    ) -> AIDecision:
        """Persist a Decision recommendation into the ai_decisions table.

        Maps decision.action to decision_type using action.value.
        Puts the full structured decision (excluding id) into payload JSONB.
        Sets status='proposed' and rationale=decision.reason.

        Args:
            session: Active asynchronous SQLAlchemy session.
            decision: Structured Decision object.
            decided_by_user_id: Optional user identifier proposing or logging the decision.

        Returns:
            Newly created and flushed AIDecision ORM instance with populated id.
        """
        payload = decision.to_dict(exclude_id=True)
        if decided_by_user_id is not None:
            payload["decided_by_user_id"] = decided_by_user_id

        orm_row = AIDecision(
            intersection_id=decision.intersection_id,
            decision_type=decision.action.value,
            payload=payload,
            status="proposed",
            applied_by=None,
            rationale=decision.reason,
        )
        session.add(orm_row)
        await session.flush()

        # Stamp persistent ID back into domain decision
        decision.id = orm_row.id
        return orm_row

    @classmethod
    async def get_history(
        cls,
        session: AsyncSession,
        intersection_id: Optional[int] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[AIDecision]:
        """Query decision records newest-first with pagination and optional intersection filter.

        Args:
            session: Active asynchronous SQLAlchemy session.
            intersection_id: Optional intersection identifier filter.
            limit: Maximum records to return (default 50).
            offset: Record offset for pagination (default 0).

        Returns:
            Sequence of AIDecision ORM rows ordered newest-first.
        """
        stmt = select(AIDecision).order_by(
            AIDecision.created_at.desc(),
            AIDecision.id.desc(),
        )
        if intersection_id is not None:
            stmt = stmt.where(AIDecision.intersection_id == intersection_id)

        stmt = stmt.offset(offset).limit(limit)
        result = await session.execute(stmt)
        return result.scalars().all()

    @classmethod
    async def transition(
        cls,
        session: AsyncSession,
        decision_id: int,
        new_status: str,
        user_id: int,
    ) -> AIDecision:
        """Enforce strict lifecycle transitions on an existing decision.

        Allowed transitions:
            proposed -> applied
            proposed -> reverted
            applied -> reverted

        Args:
            session: Active asynchronous SQLAlchemy session.
            decision_id: Target decision ID.
            new_status: Desired new status ('applied' or 'reverted').
            user_id: Identifier of authenticated user executing the transition.

        Returns:
            Updated AIDecision ORM instance.

        Raises:
            ValueError: If decision_id does not exist or transition is invalid.
        """
        stmt = select(AIDecision).where(AIDecision.id == decision_id)
        result = await session.execute(stmt)
        row = result.scalars().first()

        if row is None:
            raise ValueError(f"AIDecision with id {decision_id} not found.")

        current_status = row.status
        allowed = ALLOWED_TRANSITIONS.get(current_status, set())

        if new_status not in allowed:
            raise ValueError(
                f"Invalid status transition from '{current_status}' to '{new_status}'. "
                f"Allowed transitions for '{current_status}': {sorted(list(allowed))}"
            )

        payload = dict(row.payload) if isinstance(row.payload, dict) else {}
        now_iso = datetime.now(timezone.utc).isoformat()

        if new_status == "applied":
            row.applied_by = user_id
            payload["applied_at"] = now_iso
            payload["applied_by"] = user_id
        elif new_status == "reverted":
            payload["reverted_at"] = now_iso
            payload["reverted_by"] = user_id

        row.payload = payload
        flag_modified(row, "payload")
        row.status = new_status

        await session.flush()
        return row
