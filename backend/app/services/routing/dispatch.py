"""Priority-queued incident and emergency vehicle dispatch services.

Implements multi-attribute priority queues for active incident management and
emergency transit response, backed by batched database retrieval and audit trail logging.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import heapq
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import log_audit
from app.models.emergency import EmergencyEvent
from app.models.event import Incident

# Macroscopic severity ranking: critical > high > medium > low > unknown
SEVERITY_RANK: dict[str, int] = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
    "unknown": 0,
}


@dataclass
class DispatchItem:
    """Standardized dispatch work item representing a queued incident or emergency event.

    Attributes:
        kind: Classification of work item ('incident' or 'emergency').
        ref_id: Primary key identifier of the underlying database entity.
        severity: Assessed severity string ('critical', 'high', 'medium', 'low', 'unknown').
        priority: Emergency vehicle priority integer (e.g. 1-5, higher = more urgent), or 0 for incidents.
        created_at: UTC timestamp when the entity was recorded.
        label: Human-readable operational label summarizing the dispatch item.
    """

    kind: str
    ref_id: int
    severity: str
    priority: int
    created_at: datetime
    label: str


class DispatchQueue:
    """Heap-based priority queue governing multi-attribute emergency and incident triage.

    Traffic-engineering rationale:
        Municipal traffic operations centers must resolve simultaneous roadway events
        under strict life-safety triage principles:
        1. Event Severity: Critical multi-vehicle pileups or major artery closures take precedence.
        2. Vehicle Priority: Life-critical transit (tier-1 trauma ambulances / fire engines) outranks routine police patrols.
        3. FIFO Fairness: Among identical severity and priority rankings, older requests are resolved first.
    """

    def __init__(self) -> None:
        """Initialize an empty priority dispatch queue."""
        # Entries: (-severity_rank, -priority, created_at_timestamp, seq_counter, DispatchItem)
        self._heap: list[tuple[int, int, float, int, DispatchItem]] = []
        self._seq: int = 0

    def push_incident(self, row: Incident) -> DispatchItem:
        """Enqueue an Incident record based on severity ranking and reporting time."""
        severity = (row.severity or "unknown").strip().lower()
        rank = SEVERITY_RANK.get(severity, 0)
        priority = 0
        created_at = row.created_at or datetime.now(timezone.utc)
        ts = created_at.timestamp() if hasattr(created_at, "timestamp") else 0.0

        label = f"Incident #{row.id} [{severity.upper()}] - {row.description or 'No description'}"
        item = DispatchItem(
            kind="incident",
            ref_id=row.id,
            severity=severity,
            priority=priority,
            created_at=created_at,
            label=label,
        )

        self._seq += 1
        heapq.heappush(self._heap, (-rank, -priority, ts, self._seq, item))
        return item

    def push_emergency(
        self,
        row: EmergencyEvent,
        severity: Optional[str] = None,
    ) -> DispatchItem:
        """Enqueue an EmergencyEvent record based on vehicle priority and urgency."""
        if severity is None:
            if getattr(row, "incident", None) and getattr(row.incident, "severity", None):
                severity = row.incident.severity.strip().lower()
            elif hasattr(row, "severity") and getattr(row, "severity", None):
                severity = str(row.severity).strip().lower()
            elif getattr(row, "priority", 1) >= 3:
                severity = "critical"
            else:
                severity = "high"
        else:
            severity = severity.strip().lower()

        rank = SEVERITY_RANK.get(severity, 0)
        priority = int(row.priority) if row.priority is not None else 1
        created_at = row.created_at or datetime.now(timezone.utc)
        ts = created_at.timestamp() if hasattr(created_at, "timestamp") else 0.0

        label = f"Emergency {row.vehicle_type} (Priority {priority}) - ID #{row.id}"
        item = DispatchItem(
            kind="emergency",
            ref_id=row.id,
            severity=severity,
            priority=priority,
            created_at=created_at,
            label=label,
        )

        self._seq += 1
        heapq.heappush(self._heap, (-rank, -priority, ts, self._seq, item))
        return item

    def pop(self) -> DispatchItem:
        """Pop and return the highest priority DispatchItem.

        Raises:
            IndexError: If the queue is empty.
        """
        if not self._heap:
            raise IndexError("pop from empty DispatchQueue")
        return heapq.heappop(self._heap)[4]

    def peek(self) -> DispatchItem:
        """Return the highest priority DispatchItem without removing it.

        Raises:
            IndexError: If the queue is empty.
        """
        if not self._heap:
            raise IndexError("peek into empty DispatchQueue")
        return self._heap[0][4]

    def __len__(self) -> int:
        """Return the count of queued dispatch items."""
        return len(self._heap)

    def __bool__(self) -> bool:
        """Return True if queue has pending items, False otherwise."""
        return bool(self._heap)


async def build_dispatch_queue(session: AsyncSession) -> DispatchQueue:
    """Populate a prioritized DispatchQueue from active database incidents and emergencies.

    Performance:
        Executes exactly two batched queries with zero N+1 overhead:
        1. Incidents with status in ('reported', 'acknowledged').
        2. Active EmergencyEvent rows with linked incident eagerly pre-loaded.

    Parameters:
        session: Active asynchronous SQLAlchemy session.

    Returns:
        DispatchQueue hydrated with all pending operational events.
    """
    queue = DispatchQueue()

    # Query 1: Batched retrieval of pending incidents
    inc_stmt = (
        select(Incident)
        .where(Incident.status == "reported")
        .order_by(Incident.created_at)
    )
    inc_res = await session.execute(inc_stmt)
    incidents = inc_res.scalars().all()
    for inc in incidents:
        queue.push_incident(inc)

    # Query 2: Batched retrieval of active emergency events with eager incident loading
    em_stmt = (
        select(EmergencyEvent)
        .options(selectinload(EmergencyEvent.incident))
        .where(EmergencyEvent.status == "active")
        .order_by(EmergencyEvent.created_at)
    )
    em_res = await session.execute(em_stmt)
    emergencies = em_res.scalars().all()
    for em in emergencies:
        queue.push_emergency(em)

    return queue


async def dispatch_next(
    session: AsyncSession,
    queue: DispatchQueue,
    actor: Any = None,
) -> Optional[DispatchItem]:
    """Pop highest-priority item, transition its database state, and log an audit trail entry.

    Transitions:
        - Incident: status updated to 'acknowledged'
        - EmergencyEvent: status updated to 'dispatched'

    Parameters:
        session: Active asynchronous SQLAlchemy session.
        queue: The active DispatchQueue to draw from.
        actor: Optional user identifier (int) or user entity initiating the dispatch action.

    Returns:
        The popped DispatchItem, or None if the queue was empty.
    """
    if not queue:
        return None

    item = queue.pop()

    actor_user_id: Optional[int] = None
    if isinstance(actor, int):
        actor_user_id = actor
    elif hasattr(actor, "id") and isinstance(actor.id, int):
        actor_user_id = actor.id

    if item.kind == "incident":
        inc_stmt = select(Incident).where(Incident.id == item.ref_id)
        inc_res = await session.execute(inc_stmt)
        incident_row = inc_res.scalar_one_or_none()
        if incident_row is not None:
            incident_row.status = "acknowledged"

        await log_audit(
            db=session,
            action="incident.acknowledged",
            actor_user_id=actor_user_id,
            entity_type="incident",
            entity_id=item.ref_id,
            details={
                "kind": item.kind,
                "severity": item.severity,
                "priority": item.priority,
                "label": item.label,
                "status": "acknowledged",
            },
        )

    elif item.kind == "emergency":
        em_stmt = select(EmergencyEvent).where(EmergencyEvent.id == item.ref_id)
        em_res = await session.execute(em_stmt)
        emergency_row = em_res.scalar_one_or_none()
        if emergency_row is not None:
            emergency_row.status = "dispatched"

        await log_audit(
            db=session,
            action="emergency.dispatched",
            actor_user_id=actor_user_id,
            entity_type="emergency_event",
            entity_id=item.ref_id,
            details={
                "kind": item.kind,
                "severity": item.severity,
                "priority": item.priority,
                "label": item.label,
                "status": "dispatched",
            },
        )

    await session.commit()
    return item
