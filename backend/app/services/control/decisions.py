"""Decision engine core and live traffic state builder.

CRITICAL ARCHITECTURAL SAFETY INVARIANT:
----------------------------------------
This engine is strictly advisory, supervisory, and non-actuating.
All decisions emitted by this engine are recommendations (`is_recommendation=True`).
The system NEVER claims direct hardware controller actuation, overrides local
conflict monitors, or bypasses physical failsafes. All actions are submitted as
proposals requiring human supervisory approval or compliant NTCIP field translation.
"""

from datetime import datetime, timezone
import logging
from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.emergency import EmergencyEvent
from app.models.event import Incident
from app.models.road import Road
from app.models.signal import Signal, SignalPhase
from app.models.traffic import TrafficRecord
from app.services.control.exceptions import StaleTelemetryError
from app.services.control.rules import (
    CONFIDENCE_EMERGENCY,
    CONFIDENCE_REROUTE_DEFAULT,
    CONFIDENCE_SPLIT_ADJUSTMENT,
    DENSITY_REDUCE_GREEN_THRESHOLD,
    QUEUE_GROWTH_REROUTE_THRESHOLD,
    QUEUE_LENGTH_EXTEND_GREEN_THRESHOLD,
    QUEUE_LENGTH_REDUCE_GREEN_THRESHOLD,
    QUEUE_LENGTH_REROUTE_THRESHOLD,
    evaluate_control_rules,
    query_signals_for_intersection,
)
from app.services.control.schemas import (
    Decision,
    DecisionAction,
    PredictedState,
    TrafficState,
)

logger = logging.getLogger(__name__)

__all__ = [
    "TrafficStateBuilder",
    "DecisionEngine",
    "evaluate_control_rules",
    "query_signals_for_intersection",
    "QUEUE_LENGTH_REROUTE_THRESHOLD",
    "QUEUE_GROWTH_REROUTE_THRESHOLD",
    "QUEUE_LENGTH_EXTEND_GREEN_THRESHOLD",
    "DENSITY_REDUCE_GREEN_THRESHOLD",
    "QUEUE_LENGTH_REDUCE_GREEN_THRESHOLD",
    "CONFIDENCE_EMERGENCY",
    "CONFIDENCE_REROUTE_DEFAULT",
    "CONFIDENCE_SPLIT_ADJUSTMENT",
]


class TrafficStateBuilder:
    """Assembles a real TrafficState from current operational database telemetry."""

    @classmethod
    async def build(
        cls,
        session: AsyncSession,
        intersection_id: int,
        max_telemetry_age_s: float = 300.0,
    ) -> TrafficState:
        """Assemble a TrafficState from real database telemetry.

        Queries:
        1. The latest traffic_records row for the intersection.
        2. Count of open (non-resolved) incidents.
        3. Active emergency events nearby (at junction or immediate neighbors).
        4. The latest signal observation (signals.observed_state) and active phase.

        Args:
            session: Active asynchronous SQLAlchemy session.
            intersection_id: Identifier of the junction to inspect.
            max_telemetry_age_s: Maximum permissible telemetry age in seconds (default 300).

        Returns:
            Frozen TrafficState dataclass populated from live records.

        Raises:
            StaleTelemetryError: If no traffic records exist or the latest record exceeds
                max_telemetry_age_s.
        """
        # 1. Fetch latest traffic record for the junction
        record_stmt = (
            select(TrafficRecord)
            .where(TrafficRecord.intersection_id == intersection_id)
            .order_by(TrafficRecord.recorded_at.desc(), TrafficRecord.id.desc())
            .limit(1)
        )
        record_res = await session.execute(record_stmt)
        record = record_res.scalars().first()

        if record is None:
            raise StaleTelemetryError(
                intersection_id=intersection_id,
                age_s=None,
                max_telemetry_age_s=max_telemetry_age_s,
            )

        now = datetime.now(timezone.utc)
        rec_time = record.recorded_at
        if rec_time.tzinfo is None:
            rec_time = rec_time.replace(tzinfo=timezone.utc)
        telemetry_age_s = max(0.0, (now - rec_time).total_seconds())

        if telemetry_age_s > max_telemetry_age_s:
            raise StaleTelemetryError(
                intersection_id=intersection_id,
                age_s=telemetry_age_s,
                max_telemetry_age_s=max_telemetry_age_s,
            )

        # 2. Count open (non-resolved) incidents at this intersection
        incident_stmt = (
            select(func.count(Incident.id))
            .where(
                Incident.intersection_id == intersection_id,
                Incident.status != "resolved",
            )
        )
        incident_res = await session.execute(incident_stmt)
        incident_count = int(incident_res.scalar() or 0)

        # 3. Check for active emergency events nearby (connected roads)
        road_stmt = select(Road.from_intersection_id, Road.to_intersection_id).where(
            (Road.from_intersection_id == intersection_id)
            | (Road.to_intersection_id == intersection_id)
        )
        road_res = await session.execute(road_stmt)
        nearby_junctions = {intersection_id}
        for f_id, t_id in road_res.all():
            if f_id is not None:
                nearby_junctions.add(f_id)
            if t_id is not None:
                nearby_junctions.add(t_id)

        emergency_stmt = (
            select(func.count(EmergencyEvent.id))
            .select_from(EmergencyEvent)
            .join(Incident, EmergencyEvent.incident_id == Incident.id)
            .where(
                Incident.intersection_id.in_(list(nearby_junctions)),
                EmergencyEvent.status.in_(["active", "dispatched", "on_scene"]),
                EmergencyEvent.status != "resolved",
            )
        )
        emergency_res = await session.execute(emergency_stmt)
        active_emergency = bool((emergency_res.scalar() or 0) > 0)

        # 4. Fetch latest signal observation and active phase
        signal_stmt = (
            select(Signal)
            .where(Signal.intersection_id == intersection_id)
            .order_by(
                Signal.observed_at.desc().nullslast(),
                Signal.updated_at.desc(),
                Signal.id.desc(),
            )
            .limit(1)
        )
        signal_res = await session.execute(signal_stmt)
        signal = signal_res.scalars().first()

        observed_signal_state: Optional[str] = None
        current_phase_name: Optional[str] = None
        current_green_elapsed_s: Optional[float] = None

        if signal is not None:
            observed_signal_state = signal.observed_state

            phase_stmt = (
                select(SignalPhase)
                .where(
                    (SignalPhase.signal_id == signal.id)
                    | (SignalPhase.intersection_id == intersection_id),
                    SignalPhase.is_active.is_(True),
                )
                .order_by(SignalPhase.phase_order.asc(), SignalPhase.id.asc())
                .limit(1)
            )
            phase_res = await session.execute(phase_stmt)
            phase = phase_res.scalars().first()
            if phase is not None:
                current_phase_name = phase.name

        # Map metrics with honesty: missing optional pieces become None, never fabricated
        vehicle_count = int(record.vehicle_count)
        avg_speed_kmh = (
            float(record.avg_speed_kmh) if record.avg_speed_kmh is not None else None
        )

        occupancy = float(
            getattr(record, "occupancy", None)
            if getattr(record, "occupancy", None) is not None
            else (getattr(record, "congestion_level", 0) / 100.0)
        )
        density = float(
            getattr(record, "density", None)
            if getattr(record, "density", None) is not None
            else getattr(record, "vehicle_count", 0.0)
        )
        queue_length = float(
            getattr(record, "queue_length", None)
            if getattr(record, "queue_length", None) is not None
            else max(
                0.0,
                (getattr(record, "congestion_level", 0) / 100.0)
                * getattr(record, "vehicle_count", 0),
            )
        )
        source = str(record.source or "sensor")

        return TrafficState(
            intersection_id=intersection_id,
            vehicle_count=vehicle_count,
            density=density,
            queue_length=queue_length,
            occupancy=occupancy,
            avg_speed_kmh=avg_speed_kmh,
            incident_count=incident_count,
            active_emergency=active_emergency,
            observed_signal_state=observed_signal_state,
            current_phase_name=current_phase_name,
            current_green_elapsed_s=current_green_elapsed_s,
            telemetry_age_s=round(telemetry_age_s, 2),
            source=source,
        )


class DecisionEngine:
    """Core supervisory decision engine.

    Evaluates live traffic state and predictive horizons to propose advisory control
    actions conforming to NTCIP signal conventions.

    CRITICAL ARCHITECTURAL SAFETY INVARIANT:
    All decisions returned by this engine are recommendations (`is_recommendation=True`).
    The engine NEVER claims direct hardware actuation.
    """

    def __init__(
        self,
        max_telemetry_age_s: float = 300.0,
        signal_cache: Optional[dict[int, list[int]]] = None,
    ) -> None:
        """Initialize the decision engine.

        Args:
            max_telemetry_age_s: Maximum telemetry age threshold in seconds.
            signal_cache: Optional pre-populated mapping of intersection_id -> signal IDs.
        """
        self.max_telemetry_age_s = max_telemetry_age_s
        self.signal_cache: dict[int, list[int]] = dict(signal_cache) if signal_cache is not None else {}

    def register_signals(self, intersection_id: int, signal_ids: Sequence[int]) -> None:
        """Register signal controller IDs for an intersection in the local cache.

        Args:
            intersection_id: Identifier of the junction.
            signal_ids: Sequence of signal controller IDs.
        """
        self.signal_cache[intersection_id] = list(signal_ids)

    async def load_signals_for_intersection(
        self, session: AsyncSession, intersection_id: int
    ) -> list[int]:
        """Query real signals installed at an intersection and populate internal cache.

        Args:
            session: Active asynchronous database session.
            intersection_id: Identifier of the junction.

        Returns:
            List of signal controller IDs installed at the junction.
        """
        signals = await query_signals_for_intersection(session, intersection_id)
        self.signal_cache[intersection_id] = signals
        return signals

    async def propose_with_session(
        self,
        session: AsyncSession,
        state: Optional[TrafficState],
        predicted: Optional[PredictedState] = None,
    ) -> Decision:
        """Evaluate traffic telemetry after ensuring real signal IDs are cached.

        Args:
            session: Active asynchronous database session.
            state: Observed traffic state (or None if unavailable).
            predicted: Optional predictive horizon context.

        Returns:
            Advisory Decision recommendation.
        """
        if state is not None and state.intersection_id not in self.signal_cache:
            await self.load_signals_for_intersection(session, state.intersection_id)
        return self.propose(state, predicted)

    def _evaluate_rules(
        self,
        state: TrafficState,
        predicted: Optional[PredictedState],
    ) -> Optional[Decision]:
        """Evaluate deterministic priority-ordered control rules.

        Priority hierarchy:
        1. state.active_emergency -> PRIORITIZE_EMERGENCY
        2. queue >= 25 and predicted queue_growth > 2.0 -> REROUTE_TRAFFIC
        3. queue >= 15 -> EXTEND_GREEN
        4. density <= 0.15 and queue <= 3 -> REDUCE_GREEN
        5. Else -> NO_ACTION

        Args:
            state: Fresh, valid observed traffic state.
            predicted: Optional predictive horizon context.

        Returns:
            A recommended Decision based on rule evaluation.
        """
        affected_signals = self.signal_cache.get(state.intersection_id, [])
        return evaluate_control_rules(
            state=state,
            predicted=predicted,
            affected_signal_ids=affected_signals,
        )

    def propose(
        self,
        state: Optional[TrafficState],
        predicted: Optional[PredictedState] = None,
    ) -> Decision:
        """Evaluate traffic telemetry and propose an advisory control action.

        Returns a NO_ACTION decision with an explanatory reason when:
        - state is None (insufficient data)
        - telemetry is stale (defensive fallback even if builder raises)
        - nominal conditions without active emergency or congestion triggers

        Args:
            state: Observed traffic state (or None if unavailable).
            predicted: Optional predictive horizon context.

        Returns:
            Advisory Decision recommendation.
        """
        # Case 1: Missing / None traffic state (FIRST fallback)
        if state is None:
            return Decision(
                intersection_id=0,
                action=DecisionAction.NO_ACTION,
                current=TrafficState(
                    intersection_id=0,
                    vehicle_count=0,
                    density=0.0,
                    queue_length=0.0,
                    occupancy=0.0,
                    avg_speed_kmh=None,
                    incident_count=0,
                    active_emergency=False,
                    observed_signal_state=None,
                    current_phase_name=None,
                    current_green_elapsed_s=None,
                    telemetry_age_s=0.0,
                    source="insufficient_data",
                ),
                predicted=predicted,
                reason="Traffic state is missing or None; insufficient data to propose control action.",
                expected_impact="No operational change; monitoring traffic state.",
                confidence=None,
                affected_signal_ids=[],
                affected_route=None,
                model_version=predicted.model_version if predicted else None,
                is_recommendation=True,
            )

        # Case 2: Stale telemetry defense (SECOND fallback)
        if state.telemetry_age_s > self.max_telemetry_age_s:
            return Decision(
                intersection_id=state.intersection_id,
                action=DecisionAction.NO_ACTION,
                current=state,
                predicted=predicted,
                reason=(
                    f"Telemetry for intersection {state.intersection_id} is stale: "
                    f"age ({state.telemetry_age_s:.1f}s) exceeds maximum threshold "
                    f"({self.max_telemetry_age_s:.1f}s); insufficient fresh data to propose control action."
                ),
                expected_impact="No operational change; awaiting fresh telemetry before adjusting timings.",
                confidence=None,
                affected_signal_ids=[],
                affected_route=None,
                model_version=predicted.model_version if predicted else None,
                is_recommendation=True,
            )

        # Case 3: Domain rules extension hook
        rule_decision = self._evaluate_rules(state, predicted)
        if rule_decision is not None:
            return rule_decision

        # Case 4: Nominal operating conditions — no actionable condition
        return Decision(
            intersection_id=state.intersection_id,
            action=DecisionAction.NO_ACTION,
            current=state,
            predicted=predicted,
            reason="Traffic telemetry within nominal operating thresholds; no control action warranted.",
            expected_impact="Maintain current signal timing and phase progression.",
            confidence=None,
            affected_signal_ids=[],
            affected_route=None,
            model_version=predicted.model_version if predicted else None,
            is_recommendation=True,
        )
